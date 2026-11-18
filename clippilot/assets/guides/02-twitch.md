# Get your Twitch Client ID and Secret

ClipPilot uses the official Twitch Helix API to search categories and list top clips. You create your own free "application" on Twitch's developer console, which gives you a Client ID and a Client Secret.

## 1. Turn on two-factor authentication

Twitch requires 2FA before you can register apps.

1. Go to <https://www.twitch.tv/settings/security>.
2. Under **Two-Factor Authentication**, click **Set Up Two-Factor Authentication** and follow the steps.

## 2. Register an application

1. Open the developer console: <https://dev.twitch.tv/console/apps> and log in.
2. Click **Register Your Application** (or **+ Register Your Application**).
3. Fill in:
   * **Name:** anything unique, for example `ClipPilot-yourname`. Twitch names must be globally unique.
   * **OAuth Redirect URLs:** `http://localhost`. ClipPilot doesn't use it, but the field is required.
   * **Category:** `Application Integration`.
   * **Client Type:** `Confidential`. Confidential is required to get a secret.
4. Complete the captcha and click **Create**.

## 3. Copy the Client ID and create a secret

1. In the app list, click **Manage** next to your new app.
2. Copy the **Client ID**.
3. Click **New Secret** and copy the **Client Secret**. Twitch shows it only once. If you lose it, just create a new one.

## 4. Paste them into ClipPilot

1. In ClipPilot open **Settings → Twitch**.
2. Paste the Client ID and the Client Secret, then click **Save**.
3. Click **Test**. You should see "Twitch connected".

The keys are stored in your operating system's keychain. ClipPilot uses them only to get an *app access token* from `id.twitch.tv` and to call `api.twitch.tv`.

## Troubleshooting

* **"Twitch rejected the Client ID / Secret"**: the secret was mistyped or regenerated. Create a new secret and paste it again.
* **No clips found**: lower the category's *minimum views* or widen the *clip age window*. Small categories may have few clips in 48 hours.
