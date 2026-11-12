# Accounts and personal settings

Open **Settings** to manage your profile, sign-in methods, language, API keys
and connected applications.

## Accounts

Register from the sign-in page if registration is open, or follow a group
invitation link. Otherwise, ask the instance administrator to create an account.
If the page offers **Request an account**, verify your mailbox and wait for
administrator approval before choosing a password and signing in. See the
[registration steps](../web-interface.md). An invitation does not bypass approval.

Sign in with a password, a passkey, or an institutional provider when offered.
An instance may require institutional sign-in and hide local sign-in options.

If you already have an account, connect an institutional provider under
**Settings → Sign-in and security** before using it to sign in. Matching email
addresses do not link accounts automatically.

**Forgot your password?** Use the reset link on the sign-in page if it is
available. Self-service reset needs a confirmed email address. Otherwise, ask
the administrator for a reset.

After repeated incorrect passwords or codes, sign-in pauses for up to five
minutes. Wait before retrying; reloading or requesting another code does not
clear the pause.

## Account settings

Use **Profile** to change your display name, email address and publication
visibility. Confirm a new email address using the link altero sends you.

Under **Sign-in and security**, you can change your password, manage sign-in
methods and sign out individual browser sessions. Sensitive changes may ask
you to confirm your identity again; that confirmation lasts five minutes.
On an instance that requires institutional sign-in, use your provider to confirm.

### Passkeys

A passkey lets you sign in using your device's fingerprint, face recognition
or PIN, without typing a username or password. It also satisfies identity
confirmation for sensitive actions.

Add or remove passkeys under **Sign-in and security**. Keep another way to
sign in if a passkey lives on just one device. The interface will not let you
remove your last sign-in method.

If passkeys are unavailable, ask the administrator whether they are enabled
for this server address.

### Second factors

You can add an authenticator app or email codes to password sign-in:

- **Authenticator app:** scan the setup code, then enter a code from the app to finish setup.
- **Email codes:** first confirm your email address, then enable this option. Codes expire after ten minutes and work only in the browser that requested them.

If both are enabled, altero asks for the authenticator code first. Choose
**Use a code by email instead** if you cannot access the app. Passkey sign-in
does not require an additional code. On an institutional-only instance, manage
second factors with your identity provider.

## API keys

Open **Settings → API keys** to create, review or revoke keys used by Zotero
Desktop and other tools. Each entry shows its permissions and recent use.

Copy a new key immediately: it is shown in full only once. Treat it like a
password. Revoke a key you no longer recognize or need; any client using it
will lose access immediately.

Browser sign-in and API keys are separate. To connect Zotero Desktop, use
[Link Account](../clients.md#link-the-account).

## Connected applications

**Settings → Connected applications** lists applications you have approved,
their permissions and recent use. Choose **Disconnect** to stop an application's
access immediately.

When an application asks to connect, sign in to altero, review its requested
permissions, and choose which libraries or collections it may reach. Approve
only access you intend to give. Operators can find registration instructions in
[Connecting other applications](../oauth.md).

## Language and time zone

Choose your language and time zone in **Settings**. Both preferences follow
your account across browsers; by default they follow the browser.

The interface supports regional English, Portuguese and Chinese variants, as
well as right-to-left languages. Dates follow your regional format and chosen
time zone. Library content keeps its own text direction.

Some item types and field labels may remain in English where Zotero does not
provide a translation. To report or improve wording, see the
[translation guide](https://github.com/eseifert/altero/blob/master/CONTRIBUTING.md#translating-the-interface).
