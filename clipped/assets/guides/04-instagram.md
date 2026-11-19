# Instagram Reels (optional)

clipped can post every approved Short to Instagram as a Reel, with the same title, streamer credit and links, on its own or alongside YouTube. Instagram only lets apps post to **professional** accounts, so this takes about ten minutes once.

Don't want to set anything up? Skip this. In **Review**, use **Download** and **Copy caption**, post the Short yourself, then click **Posted it myself**.

## 1. Make your account professional

In the Instagram app: **Settings → Account type and tools → Switch to professional account**. Creator or Business both work, and it's free.

## 2. Create a Meta app

1. Go to <https://developers.facebook.com/apps> and sign in with Facebook (the account doesn't have to be linked to your Instagram).
2. **Create app** → use case **Other** → app type **Business** → give it any name, e.g. *my clipped*.
3. In the app's dashboard, add the product **Instagram** and choose **API setup with Instagram login**.

## 3. Generate a token

1. Under **Generate access tokens**, click **Add account** and log in to the Instagram account you post to.
2. Click **Generate token** next to it, approve, and copy the token. It starts with `IGAA…`.

The token needs the permissions `instagram_business_basic` and `instagram_business_content_publish`; the token generator includes them.

## 4. Paste it into clipped

**Settings → Connections → Instagram Reels**, paste the token and click **Connect**. clipped checks it, shows your @username, and stores the token in your OS keychain.

Tokens last 60 days. clipped renews it by itself while the app is running, so you shouldn't need to paste it again. If Instagram ever rejects it (you changed your password, or removed the app), clipped stops posting to Instagram, says so on the dashboard, and you paste a fresh one.

## Good to know

* Your app stays in **development mode**, which is fine: it only ever posts to your own account, which you added in step 3.
* Instagram allows up to 50 posts through the API per day.
* Captions keep up to 30 hashtags and 2,200 characters; clipped trims anything over.
* If Instagram can't process a video it says why in the log, and the Short goes back to the queue to retry.
