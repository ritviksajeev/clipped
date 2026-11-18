# Connect YouTube (Google Cloud setup)

clipped uploads through the official **YouTube Data API v3** and reads performance from the **YouTube Analytics API**, using an OAuth client that **you** create in your own Google Cloud project. It's free and takes about 10 minutes. Because the project is yours, Google will show an "unverified app" warning when you sign in. That's expected: you are the developer.

> **Important: uploads may be private at first.** YouTube locks videos uploaded through API projects that haven't passed YouTube's free API compliance audit to **private**. clipped detects this and tells you. To publish publicly from the API, submit the audit form (step 7). Until then you can open each private video in YouTube Studio and switch it to Public yourself.

## 1. Create a Google Cloud project

1. Go to <https://console.cloud.google.com/> and sign in with the Google account that owns your YouTube channel.
2. Click the project picker at the top, then **New Project**. Name it `clipped` and click **Create**.
3. Make sure the new project is selected in the picker.

No billing account is needed.

## 2. Enable the two YouTube APIs

1. Open **APIs & Services → Library**: <https://console.cloud.google.com/apis/library>.
2. Search **YouTube Data API v3**, open it, and click **Enable**.
3. Search **YouTube Analytics API**, open it, and click **Enable**.

## 3. Configure the OAuth consent screen

Google calls this area **Google Auth Platform** (older consoles say **OAuth consent screen**).

1. Open <https://console.cloud.google.com/auth/overview> and click **Get started**.
2. **App information:** app name `clipped`, support email = your email.
3. **Audience:** choose **External**.
4. **Contact information:** your email. Agree to the policy and click **Create**.
5. Open **Audience** and, under **Test users**, click **Add users** and add the Google account that owns your channel.
6. Open **Data Access → Add or remove scopes** and add:
   * `https://www.googleapis.com/auth/youtube.upload`
   * `https://www.googleapis.com/auth/youtube.readonly`
   * `https://www.googleapis.com/auth/yt-analytics.readonly`

   Click **Update**, then **Save**.

### Testing vs. In production

While the app is in **Testing**, Google expires your sign-in after **7 days** and clipped will ask you to reconnect. To avoid that, open **Audience** and click **Publish app** → **Confirm**. The app stays unverified, which is fine for personal use (unverified apps are limited to 100 users). You do **not** need to submit it for Google verification.

## 4. Create the OAuth client

1. Open **Clients** (or **APIs & Services → Credentials**): <https://console.cloud.google.com/auth/clients>.
2. Click **Create client**.
3. **Application type: Desktop app**. Name it `clipped desktop` and click **Create**.
4. Click **Download JSON** (the file is named like `client_secret_….json`).

A *Desktop app* client works with clipped's local sign-in page on any port. If you choose *Web application* instead, add `http://localhost:8000/oauth2callback` as an authorized redirect URI.

## 5. Add the client to clipped

1. In clipped open **Settings → YouTube**.
2. Either paste the whole downloaded JSON into **Paste client JSON**, or copy the **Client ID** and **Client Secret** into the two fields.
3. Click **Save**.

## 6. Connect your channel

1. Click **Connect YouTube**. A Google sign-in tab opens.
2. Pick the account that owns your channel.
3. You'll see **Google hasn't verified this app**. Click **Advanced** → **Go to clipped (unsafe)**. This is your own app.
4. Allow the requested permissions.
5. You're sent back to clipped and the channel name appears in Settings.

## 7. Optional: pass the API audit so uploads can be public

1. Open the **YouTube API Services Audit and Quota Extension Form**: <https://support.google.com/youtube/contact/yt_api_form>.
2. Choose the audit option, describe clipped as "a personal tool that uploads my own edited Shorts of Twitch clips with streamer credit", and list your project number (shown on the Cloud console dashboard).
3. Google reviews it, which can take a few weeks. Once approved, uploads use the privacy you chose in Settings.

## Quota

A new project gets **10,000 units per day**, reset at midnight Pacific time. One upload costs about 1,600 units (plus 50 for a custom thumbnail), so **about 6 uploads per day**. clipped tracks this on the dashboard, stops before it runs out, and resumes after the reset. The same audit form can request more quota.

## Custom thumbnails

YouTube only accepts custom thumbnails from **phone-verified** channels (<https://www.youtube.com/verify>). If yours isn't verified, uploads still work and clipped simply skips the thumbnail. Note that the Shorts feed itself usually shows a frame from the video rather than the custom thumbnail.
