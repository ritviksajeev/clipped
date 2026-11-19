"""FastAPI app: JSON API for the dashboard + the built React app.

Security for a localhost app:
* binds to 127.0.0.1 by default (see server.py)
* Host-header allowlist blocks DNS-rebinding attacks
* every state-changing /api request must carry ``X-Clipped: 1`` (a custom
  header other websites cannot send cross-origin without a CORS preflight,
  which we never grant) - this blocks CSRF from pages open in your browser
* secrets are write-only through the API: only "set" + a masked hint come back
"""

from __future__ import annotations

import asyncio
import io
import re
import json
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import config
from ..db import Database, iso, utcnow
from ..engine import Engine, EngineError
from ..keystore import SECRET_NAMES, KeyStore
from ..logs import get_logger, live_buffer
from ..models import CategorySettings, ClipInfo, GlobalSettings, ReframeSettings, normalize_hashtags
from ..optimizer import insights
from ..pipeline import metadata
from ..services import ai
from ..services.twitch import TwitchClient, TwitchError
from ..services.youtube import AuthError, OAuthFlow, YouTubeClient, YouTubeError

log = get_logger("api")

DEFAULT_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


# --------------------------------------------------------------------------- request bodies

class SecretBody(BaseModel):
    value: str = Field("", max_length=4096)


class GoogleJsonBody(BaseModel):
    json_text: str = Field(..., max_length=20000)


class CategoryCreate(BaseModel):
    twitch_id: str
    name: str
    box_art_url: str = ""
    settings: Optional[CategorySettings] = None


class CategoryUpdate(BaseModel):
    enabled: Optional[bool] = None
    settings: Optional[CategorySettings] = None


class ItemPatch(BaseModel):
    title: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = Field(None, max_length=6000)
    hashtags: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    hook_text: Optional[str] = Field(None, max_length=80)
    thumbnail_text: Optional[str] = Field(None, max_length=120)
    commentary: Optional[str] = Field(None, max_length=300)
    chosen: Optional[int] = None
    reframe: Optional[ReframeSettings] = None


class ApproveBody(BaseModel):
    upload_now: bool = False


class ClipAdd(BaseModel):
    url: str
    category_id: Optional[int] = None


class ProviderBody(BaseModel):
    provider: str


DONE_PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title} · clipped</title><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#09090b;color:#f3f0ea;
font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:440px;padding:40px 32px;border:1px solid #27272a;border-radius:20px;background:#111113;text-align:center}}
.dot{{width:14px;height:14px;border-radius:50%;margin:0 auto 18px;background:{color};box-shadow:0 0 24px {color}}}
h1{{font-size:24px;margin:0 0 8px;font-weight:600}}p{{margin:0;color:#a1a1aa}}
a{{display:inline-block;margin-top:22px;color:#dcd6ff;font-size:14px}}</style></head>
<body><main><div class="dot"></div><h1>{title}</h1><p>{message}</p><a href="/#/settings/connections">Back to clipped</a></main></body></html>"""


def done_page(title: str, message: str, ok: bool = True) -> HTMLResponse:
    """Shown after a sign-in that started in the desktop window (in its popup or the system browser)."""
    import html as _html

    page = DONE_PAGE.format(title=_html.escape(title), message=_html.escape(message),
                            color="#8a78f0" if ok else "#f87171")
    if ok:  # a popup opened by the app window closes itself; elsewhere this does nothing
        page = page.replace("</body>", "<script>setTimeout(function(){window.close()},1500)</script></body>")
    return HTMLResponse(page, status_code=200 if ok else 400)


class PauseBody(BaseModel):
    until: Optional[datetime] = None


# --------------------------------------------------------------------------- helpers

def item_view(item: dict) -> dict:
    if not item:
        return item
    out = dict(item)
    version = re.sub(r"\D", "", item.get("updated_at") or "")  # cache-buster after re-renders
    out["video_url"] = f"/media/items/{item['id']}/video.mp4?v={version}" if item.get("video_path") else ""
    out["thumbnail_url"] = f"/media/items/{item['id']}/thumbnail.jpg?v={version}" if item.get("thumbnail_path") else ""
    out["youtube_url"] = f"https://youtube.com/shorts/{item['youtube_id']}" if item.get("youtube_id") else ""
    for key in ("workdir", "video_path", "thumbnail_path"):
        out.pop(key, None)
    return out


def _clip_for(db: Database, item: dict) -> ClipInfo:
    row = db.get_clip(item["clip_id"])
    return row["clip"] if row else ClipInfo(id=item["clip_id"], broadcaster_name=item["streamer"])


def needs_auto_ack(gs: GlobalSettings, categories: list[dict]) -> bool:
    any_auto = gs.mode == "auto" or any(c["settings"].get("mode") == "auto" for c in categories)
    return any_auto and gs.auto_warning_acknowledged_at is None


def create_app(*, db: Database | None = None, store: KeyStore | None = None, engine: Engine | None = None,
               allowed_hosts: set[str] | None = None, autostart: bool = True, app_session=None) -> FastAPI:
    db = db or Database(config.db_path())
    store = store or KeyStore()
    engine = engine or Engine(db, store)
    hosts = set(allowed_hosts or DEFAULT_ALLOWED_HOSTS)
    hosts |= {h.strip() for h in os.environ.get("CLIPPED_ALLOWED_HOSTS", "").split(",") if h.strip()}
    pending_auth: dict[str, Any] = {}
    desktop_flows: set[str] = set()  # sign-ins started from the desktop window finish in the system browser
    ant_login = ai.AnthropicLogin()
    openrouter_flow = ai.OpenRouterConnect()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        reset = db.reset_stuck_items()
        if reset:
            log.info("Recovered %d item(s) interrupted by the last shutdown", reset)
        if autostart and db.get_value("engine_running", False):
            await engine.start()
        yield
        if engine.running:
            await engine.stop()
        engine.shutdown()

    app = FastAPI(title="clipped", version=config.APP_VERSION, lifespan=lifespan, docs_url="/api/docs",
                  redoc_url=None, openapi_url="/api/openapi.json")
    app.state.db, app.state.store, app.state.engine = db, store, engine

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.headers.get("host", "")
        hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        if hostname not in hosts:
            return JSONResponse({"detail": "Host not allowed"}, status_code=403)
        if request.method not in SAFE_METHODS and request.url.path.startswith("/api/"):
            if request.headers.get("x-clipped") != "1":
                return JSONResponse({"detail": "Missing X-Clipped header"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.exception_handler(EngineError)
    async def engine_error(_: Request, exc: EngineError):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    # ------------------------------------------------------------------ desktop window heartbeat
    @app.post("/app/ping")
    def app_ping(token: str = "", bye: bool = False, away: bool = False):
        # Outside /api so navigator.sendBeacon (which cannot set headers) works
        # when the window closes; the per-launch token stops other sites from
        # faking it.
        if app_session is None or not app_session.ping(token, bye=bye, away=away):
            raise HTTPException(404, "Not found")
        return {"ok": True}

    # ------------------------------------------------------------------ status & engine
    @app.get("/api/status")
    def status():
        data = engine.status()
        data["version"] = config.APP_VERSION
        data["ffmpeg"] = bool(config.find_binary("ffmpeg"))
        data["auto_warning_acknowledged"] = db.get_global_settings().auto_warning_acknowledged_at is not None
        return data

    @app.get("/api/about")
    def about():
        from ..pipeline.ffmpeg import has_libass

        ff = config.find_binary("ffmpeg")
        return {"version": config.APP_VERSION, "data_dir": str(config.data_dir()), "ffmpeg": ff,
                "libass": bool(ff) and has_libass(), "secret_storage": store.backend_name}

    @app.post("/api/engine/start")
    async def engine_start():
        if not config.find_binary("ffmpeg"):
            raise HTTPException(400, "ffmpeg is not installed - see the setup guide")
        await engine.start()
        return engine.status()

    @app.post("/api/engine/stop")
    async def engine_stop():
        await engine.stop()
        return engine.status()

    @app.post("/api/engine/pause")
    def engine_pause(body: PauseBody):
        gs = db.get_global_settings()
        gs.schedule.pause_until = body.until
        db.save_global_settings(gs)
        log.info("Uploads paused until %s", body.until) if body.until else log.info("Uploads resumed")
        return engine.status()

    # ------------------------------------------------------------------ logs
    @app.get("/api/logs")
    def logs(after: int = 0, limit: int = Query(300, le=1500)):
        return [e for e in live_buffer.tail(limit) if e["seq"] > after]

    @app.get("/api/logs/stream")
    async def logs_stream(request: Request):
        queue = live_buffer.subscribe()

        async def events():
            try:
                for entry in live_buffer.tail(200):
                    yield f"data: {json.dumps(entry)}\n\n"
                while not await request.is_disconnected():
                    try:
                        entry = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"data: {json.dumps(entry)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                live_buffer.unsubscribe(queue)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------------ settings
    @app.get("/api/settings")
    def get_settings():
        gs = db.get_global_settings()
        return {"settings": gs.model_dump(mode="json"),
                "auto_warning_acknowledged": gs.auto_warning_acknowledged_at is not None}

    @app.put("/api/settings")
    def put_settings(settings: GlobalSettings):
        current = db.get_global_settings()
        settings.auto_warning_acknowledged_at = current.auto_warning_acknowledged_at
        if needs_auto_ack(settings, db.list_categories()):
            raise HTTPException(409, "auto_warning_required")
        db.save_global_settings(settings)
        log.info("Settings saved")
        return {"settings": settings.model_dump(mode="json"), "auto_warning_acknowledged":
                settings.auto_warning_acknowledged_at is not None}

    @app.post("/api/settings/acknowledge-auto")
    def acknowledge_auto():
        gs = db.get_global_settings()
        if gs.auto_warning_acknowledged_at is None:
            gs.auto_warning_acknowledged_at = utcnow()
            db.save_global_settings(gs)
            log.info("Auto mode responsibility notice acknowledged")
        return {"auto_warning_acknowledged": True}

    # ------------------------------------------------------------------ secrets
    @app.get("/api/secrets")
    def secrets_status():
        return {"backend": store.backend_name, "os_keyring": store.is_os_keyring, "secrets": store.status()}

    @app.put("/api/secrets/{name}")
    def set_secret(name: str, body: SecretBody):
        if name not in SECRET_NAMES or name == "youtube_refresh_token":
            raise HTTPException(404, "Unknown secret")
        store.set(name, body.value)
        if name.startswith("google_") or name.startswith("twitch_"):
            engine.auth_problem = ""
        return store.status()[name]

    @app.delete("/api/secrets/{name}")
    def delete_secret(name: str):
        if name not in SECRET_NAMES:
            raise HTTPException(404, "Unknown secret")
        store.delete(name)
        return store.status()[name]

    @app.post("/api/secrets/google-client-json")
    def google_client_json(body: GoogleJsonBody):
        """Accept the client_secret_*.json file Google Cloud lets you download."""
        try:
            data = json.loads(body.json_text)
            block = data.get("installed") or data.get("web") or data
            client_id, client_secret = block["client_id"], block["client_secret"]
        except (ValueError, KeyError, AttributeError, TypeError):
            raise HTTPException(400, "That file doesn't look like a Google OAuth client JSON")
        store.set("google_client_id", client_id)
        store.set("google_client_secret", client_secret)
        engine.auth_problem = ""
        return {"google_client_id": store.status()["google_client_id"],
                "google_client_secret": store.status()["google_client_secret"],
                "client_type": "desktop" if "installed" in data else "web" if "web" in data else "unknown"}

    # ------------------------------------------------------------------ twitch & categories
    @app.post("/api/twitch/test")
    def twitch_test():
        try:
            client = TwitchClient.from_keystore(store)
            client.validate()
            client.close()
        except TwitchError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True}

    @app.get("/api/twitch/search")
    def twitch_search(q: str = ""):
        try:
            client = TwitchClient.from_keystore(store)
            try:
                return client.search_categories(q)
            finally:
                client.close()
        except TwitchError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/categories")
    def list_categories():
        cats = db.list_categories()
        counts = {r["category_id"]: r["n"] for r in db.query(
            "SELECT category_id, COUNT(*) AS n FROM items WHERE status='uploaded' GROUP BY category_id")}
        for c in cats:
            c["uploads"] = counts.get(c["id"], 0)
        return cats

    @app.post("/api/categories")
    def add_category(body: CategoryCreate):
        settings = body.settings or CategorySettings()
        gs = db.get_global_settings()
        if settings.mode == "auto" and gs.auto_warning_acknowledged_at is None:
            raise HTTPException(409, "auto_warning_required")
        cat = db.add_category(body.twitch_id, body.name, body.box_art_url, settings)
        log.info("Added category %s", body.name)
        return cat

    @app.put("/api/categories/{category_id}")
    def update_category(category_id: int, body: CategoryUpdate):
        if not db.get_category(category_id):
            raise HTTPException(404, "Category not found")
        if body.settings and body.settings.mode == "auto" and db.get_global_settings().auto_warning_acknowledged_at is None:
            raise HTTPException(409, "auto_warning_required")
        return db.update_category(category_id, enabled=body.enabled, settings=body.settings)

    @app.delete("/api/categories/{category_id}")
    def delete_category(category_id: int):
        db.delete_category(category_id)
        return {"ok": True}

    @app.post("/api/categories/{category_id}/fetch", status_code=202)
    def fetch_category(category_id: int):
        if not engine.twitch_ready():
            raise HTTPException(400, "Add your Twitch Client ID and Secret first")
        engine.run_now("net", engine.fetch_due, category_id)
        return {"queued": True}

    # ------------------------------------------------------------------ youtube
    @app.get("/api/youtube/status")
    def youtube_status():
        return {"connected": bool(store.get("youtube_refresh_token")), "channel": db.get_value("youtube_channel"),
                "client_configured": bool(store.get("google_client_id") and store.get("google_client_secret")),
                "auth_problem": engine.auth_problem}

    @app.get("/api/youtube/connect")
    def youtube_connect(request: Request, desktop: bool = False):
        redirect_uri = str(request.base_url).rstrip("/") + "/oauth2callback"
        try:
            flow = OAuthFlow(store.get("google_client_id") or "", store.get("google_client_secret") or "", redirect_uri)
        except AuthError as exc:
            raise HTTPException(400, str(exc))
        url, pending = flow.start()
        now = time.time()
        for key in [k for k, v in pending_auth.items() if now - v.created > 900]:
            pending_auth.pop(key, None)
        pending_auth[pending.state] = pending
        if desktop:
            desktop_flows.add(pending.state)
        return {"url": url, "redirect_uri": redirect_uri}

    @app.get("/oauth2callback")
    def oauth_callback(state: str = "", code: str = "", error: str = ""):
        pending = pending_auth.pop(state, None)
        desktop = state in desktop_flows
        desktop_flows.discard(state)

        def fail(reason: str):
            log.warning("YouTube connect failed: %s", reason)
            if desktop:
                return done_page("YouTube not connected", f"{reason}. Go back to clipped and try again.", ok=False)
            return RedirectResponse(f"/#/settings?youtube_error={reason}", status_code=303)

        if error or not pending or not code:
            return fail(error or ("expired or unknown sign-in attempt" if not pending else "no code returned"))
        try:
            flow = OAuthFlow(store.get("google_client_id") or "", store.get("google_client_secret") or "",
                             pending.redirect_uri)
            tokens = flow.exchange(code, pending)
            store.set("youtube_refresh_token", tokens["refresh_token"])
            engine.auth_problem = ""
            yt = YouTubeClient.from_keystore(store, quota=engine.quota)
            try:
                channel = yt.channel()
                db.set_value("youtube_channel", channel)
                log.info("Connected YouTube channel “%s”", channel["title"])
            finally:
                yt.close()
        except (AuthError, YouTubeError) as exc:
            return fail(str(exc)[:200])
        if desktop:
            return done_page("YouTube connected", "You can close this tab and go back to clipped.")
        return RedirectResponse("/#/settings?youtube=connected", status_code=303)

    # ------------------------------------------------------------------ AI connections (titles)
    def use_provider_if_unset(provider: str) -> None:
        gs = db.get_global_settings()
        if gs.metadata.provider == "template":
            gs.metadata.provider = provider
            db.save_global_settings(gs)
            log.info("Titles will now be written by %s", provider)

    @app.get("/api/ai/status")
    def ai_status():
        gs = db.get_global_settings()
        keys = store.status()
        profile = ai.anthropic_profile()
        login = ant_login.snapshot()
        if login["state"] == "done":
            use_provider_if_unset("anthropic")
            gs = db.get_global_settings()
        return {
            "provider": gs.metadata.provider,
            "anthropic": {**profile, "api_key": keys["anthropic_api_key"]["set"], "env": ai.anthropic_env_key(),
                          "login": login, "ready": profile["signed_in"] or keys["anthropic_api_key"]["set"]
                          or ai.anthropic_env_key()},
            "openrouter": {"connected": keys["openrouter_api_key"]["set"], "hint": keys["openrouter_api_key"]["hint"]},
            "openai": {"ready": keys["openai_api_key"]["set"]},
            "ollama": ai.ollama_status(gs.metadata.ollama_url),
        }

    @app.post("/api/ai/anthropic/login")
    def anthropic_login():
        try:
            return ant_login.start()
        except ai.AIConnectError as exc:
            raise HTTPException(400, str(exc))
        except OSError as exc:
            raise HTTPException(500, f"Could not start the Anthropic CLI: {exc}")

    @app.post("/api/ai/openrouter/connect")
    def openrouter_connect(request: Request, desktop: bool = False):
        # OpenRouter documents localhost callbacks for local apps, so use that name.
        port = request.url.port or 80
        callback = f"http://localhost:{port}/openrouter/callback"
        return {"url": openrouter_flow.start(callback, desktop)}

    @app.get("/openrouter/callback")
    def openrouter_callback(code: str = "", error: str = ""):
        desktop = openrouter_flow.desktop
        try:
            if error or not code:
                raise ai.AIConnectError(error or "OpenRouter did not return a code")
            key = openrouter_flow.finish(code)
        except ai.AIConnectError as exc:
            log.warning("OpenRouter connect failed: %s", exc)
            if desktop:
                return done_page("OpenRouter not connected", str(exc), ok=False)
            return RedirectResponse(f"/#/settings?ai_error={str(exc)[:200]}", status_code=303)
        store.set("openrouter_api_key", key)
        use_provider_if_unset("openrouter")
        log.info("Connected OpenRouter")
        if desktop:
            return done_page("OpenRouter connected", "You can close this tab and go back to clipped.")
        return RedirectResponse("/#/settings?ai=openrouter", status_code=303)

    @app.post("/api/ai/openrouter/disconnect")
    def openrouter_disconnect():
        store.delete("openrouter_api_key")
        gs = db.get_global_settings()
        if gs.metadata.provider == "openrouter":
            gs.metadata.provider = "template"
            db.save_global_settings(gs)
        return {"connected": False}

    @app.post("/api/ai/use")
    def ai_use(body: ProviderBody):
        status = ai_status()
        ready = {"template": True, "anthropic": status["anthropic"]["ready"], "openai": status["openai"]["ready"],
                 "openrouter": status["openrouter"]["connected"], "ollama": status["ollama"]["running"]}
        if body.provider not in ready:
            raise HTTPException(400, "Unknown provider")
        if not ready[body.provider]:
            raise HTTPException(400, f"Connect {body.provider} first")
        gs = db.get_global_settings()
        gs.metadata.provider = body.provider  # type: ignore[assignment]
        db.save_global_settings(gs)
        return {"provider": body.provider, "settings": gs.model_dump(mode="json")}

    @app.post("/api/youtube/disconnect")
    def youtube_disconnect():
        token = store.get("youtube_refresh_token")
        if token:
            try:
                YouTubeClient.from_keystore(store).revoke()
            except AuthError:
                pass
        store.delete("youtube_refresh_token")
        db.set_value("youtube_channel", None)
        log.info("YouTube disconnected")
        return {"connected": False}

    @app.post("/api/youtube/refresh-stats", status_code=202)
    def refresh_stats():
        engine.run_now("net", engine.refresh_stats_due, True)
        return {"queued": True}

    # ------------------------------------------------------------------ review queue & items
    @app.get("/api/items")
    def list_items(status: str = "", limit: int = Query(100, le=500), offset: int = 0):
        statuses = [s for s in status.split(",") if s] or None
        return [item_view(i) for i in db.list_items(statuses, limit=limit, offset=offset)]

    @app.get("/api/items/{item_id}")
    def get_item(item_id: int):
        item = db.get_item(item_id)
        if not item:
            raise HTTPException(404, "Item not found")
        view = item_view(item)
        view["stats"] = db.stats_for(item_id)
        clip = db.get_clip(item["clip_id"])
        if clip:
            view["clip"] = clip["clip"].model_dump(mode="json")
            view["clip"]["channel_url"] = clip["clip"].channel_url
        else:
            view["clip"] = None
        return view

    @app.patch("/api/items/{item_id}")
    def patch_item(item_id: int, body: ItemPatch):
        item = db.get_item(item_id)
        if not item:
            raise HTTPException(404, "Item not found")
        if item["status"] in ("uploading", "uploaded"):
            raise HTTPException(409, "Already uploaded")
        gs = db.get_global_settings()
        clip = _clip_for(db, item)
        fields: dict[str, Any] = {}
        if body.chosen is not None and 0 <= body.chosen < len(item["variants"]):
            v = metadata.Variant.from_dict(item["variants"][body.chosen])
            fields.update(chosen=body.chosen, title=v.title, description=v.description, tags=v.tags,
                          title_style=v.style)
            if v.hook_text != item["hook_text"]:
                fields.update(hook_text=v.hook_text, needs_rerender=True)
        if body.title is not None:
            fields["title"] = body.title
        if body.description is not None:
            fields["description"] = body.description
        if body.hashtags is not None:
            tags = normalize_hashtags(body.hashtags)
            desc = fields.get("description", item["description"])
            lines = [l for l in desc.splitlines() if not l.strip().startswith("#")]
            fields["description"] = "\n".join(lines).rstrip() + "\n\n" + " ".join(tags)
            fields["tags"] = metadata.build_tags(tags, clip)
        if body.tags is not None:
            fields["tags"] = [t.strip() for t in body.tags if t.strip()][:30]
        for key in ("hook_text", "thumbnail_text", "commentary"):
            value = getattr(body, key)
            if value is not None and value != item[key]:
                fields[key] = value
                fields["needs_rerender"] = True
        if body.reframe is not None:
            analysis = dict(item["analysis"])
            analysis["reframe_override"] = body.reframe.model_dump(mode="json")
            fields.update(analysis=analysis, needs_rerender=True)
        if "title" in fields or "description" in fields:
            fields["title"], fields["description"] = metadata.ensure_credit(
                fields.get("title", item["title"]), fields.get("description", item["description"]), clip,
                gs.metadata.credit_in_title)
        return item_view(db.update_item(item_id, **fields) if fields else item)

    @app.post("/api/items/{item_id}/approve")
    def approve(item_id: int, body: ApproveBody = Body(default_factory=ApproveBody)):
        item = db.get_item(item_id)
        if not item:
            raise HTTPException(404, "Item not found")
        if item["status"] not in ("review", "ready", "failed", "rejected"):
            raise HTTPException(409, f"Cannot approve an item that is {item['status']}")
        if not item["video_path"]:
            raise HTTPException(409, "This clip has no rendered video yet")
        if body.upload_now:
            engine.check_rate_limit()
        updated = db.update_item(item_id, status="approved", approved_at=utcnow(), error="", attempts=0,
                                 next_attempt_at=None)
        log.info("Approved “%s”", item["title"][:60])
        if updated["needs_rerender"]:
            engine.run_now("render", engine.rerender_item, item_id)
        if body.upload_now:
            engine.run_now("net", engine.upload_item, item_id)
        return item_view(updated)

    @app.post("/api/items/{item_id}/reject")
    def reject(item_id: int):
        return item_view(engine.reject_item(item_id))

    @app.post("/api/items/{item_id}/rerender", status_code=202)
    def rerender(item_id: int):
        if not db.get_item(item_id):
            raise HTTPException(404, "Item not found")
        engine.run_now("render", engine.rerender_item, item_id)
        return {"queued": True}

    @app.post("/api/items/{item_id}/upload-now", status_code=202)
    def upload_now(item_id: int):
        item = db.get_item(item_id)
        if not item:
            raise HTTPException(404, "Item not found")
        if item["status"] not in ("approved", "ready"):
            raise HTTPException(409, "Approve the clip first")
        if not engine.youtube_ready():
            raise HTTPException(400, "Connect YouTube first (Settings)")
        engine.check_rate_limit()
        engine.run_now("net", engine.upload_item, item_id)
        return {"queued": True}

    @app.post("/api/items/{item_id}/retry")
    def retry(item_id: int):
        item = db.get_item(item_id)
        if not item:
            raise HTTPException(404, "Item not found")
        if item["video_path"] and Path(item["video_path"]).exists():
            status = "approved" if item["approved_at"] else ("ready" if item["mode"] == "auto" else "review")
            return item_view(db.update_item(item_id, status=status, error="", attempts=0, next_attempt_at=None))
        db.delete_item(item_id)
        db.update_clip(item["clip_id"], status="new", skip_reason="")
        engine.run_now("render", engine.process_manual_clip, item["clip_id"])
        return {"requeued": True}

    @app.post("/api/items/{item_id}/thumbnail")
    async def upload_thumbnail(item_id: int, file: UploadFile = File(...)):
        from PIL import Image

        item = db.get_item(item_id)
        if not item or not item["workdir"]:
            raise HTTPException(404, "Item not found")
        data = await file.read()
        if len(data) > 15 * 1024 * 1024:
            raise HTTPException(413, "Image too large")
        try:
            img = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            raise HTTPException(400, "Not an image")
        img.thumbnail((1080, 1920))
        path = Path(item["workdir"]) / "thumbnail_custom.jpg"
        img.save(path, "JPEG", quality=88)
        return item_view(db.update_item(item_id, thumbnail_path=str(path)))

    def _media(item_id: int, key: str) -> FileResponse:
        item = db.get_item(item_id)
        if not item or not item[key] or not Path(item[key]).exists():
            raise HTTPException(404, "File not available")
        path = Path(item[key]).resolve()
        if config.data_dir().resolve() not in path.parents and not os.environ.get("CLIPPED_ALLOW_ANY_MEDIA"):
            raise HTTPException(403, "Outside data directory")
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @app.get("/media/items/{item_id}/video.mp4")
    def media_video(item_id: int):
        return _media(item_id, "video_path")

    @app.get("/media/items/{item_id}/thumbnail.jpg")
    def media_thumb(item_id: int):
        return _media(item_id, "thumbnail_path")

    # ------------------------------------------------------------------ clips
    @app.post("/api/clips", status_code=202)
    def add_clip(body: ClipAdd):
        row = engine.add_clip_by_url(body.url, body.category_id)
        engine.run_now("render", engine.process_manual_clip, row["id"])
        return {"queued": True, "clip_id": row["id"]}

    @app.get("/api/clips")
    def list_clips(status: str = "skipped", limit: int = Query(50, le=300)):
        rows = db.query("SELECT id, category_id, broadcaster_name, view_count, duration, score, status, skip_reason, "
                        "fetched_at, created_at FROM clips WHERE status=? ORDER BY fetched_at DESC LIMIT ?",
                        (status, limit))
        return rows

    # ------------------------------------------------------------------ history & insights
    @app.get("/api/history")
    def history(limit: int = Query(100, le=500)):
        latest = db.latest_stats()
        out = []
        for item in db.list_items(["uploaded"], limit=limit, order="uploaded_at DESC"):
            view = item_view(item)
            view["stats"] = latest.get(item["id"])
            out.append(view)
        return out

    @app.get("/api/insights")
    def get_insights():
        gs = db.get_global_settings()
        return insights.build(db.uploads_with_stats(since_days=120), engine.tz, gs, now=engine.clock())

    # ------------------------------------------------------------------ assets (intro/outro)
    @app.post("/api/assets")
    async def upload_asset(file: UploadFile = File(...)):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".mp4", ".mov", ".webm", ".mkv", ".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(400, "Use an MP4/MOV/WEBM video or a PNG/JPG image")
        target = config.uploads_dir() / f"{uuid.uuid4().hex[:10]}{suffix}"
        with target.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
        return {"path": str(target), "name": file.filename}

    # ------------------------------------------------------------------ guides
    @app.get("/api/guides")
    def guides():
        out = []
        for path in sorted((config.assets_dir() / "guides").glob("*.md")):
            text = path.read_text("utf-8")
            title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("# ")), path.stem)
            out.append({"slug": path.stem.split("-", 1)[-1], "title": title, "markdown": text})
        return out

    # ------------------------------------------------------------------ dashboard
    web = config.web_dir()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "media/")):
            raise HTTPException(404)
        candidate = (web / path).resolve() if path else None
        if candidate and candidate.is_file() and web.resolve() in candidate.parents:
            return FileResponse(candidate)
        index = web / "index.html"
        if index.exists():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse("<h1>clipped</h1><p>The API is running. The dashboard has not been built: "
                            "run <code>npm install && npm run build</code> in <code>frontend/</code>.</p>"
                            "<p><a href='/api/docs'>API docs</a></p>")

    return app
