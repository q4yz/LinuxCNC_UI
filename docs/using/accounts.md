# Accounts and logins

Who may do what is decided by a **role**:

| Role | May |
|------|-----|
| viewer | watch: state, camera, programs, settings — and press the E-stop |
| user | run the machine: jog, home, programs, heaters, calibration, files |
| admin | everything, including configuration, updates and users |
| agent | the assistant: reads, and asks before anything that moves or heats |

The full table: {doc}`../reference/permissions`.

## The default login

Like SSH on a fresh system, there is always a login: user **`remora`**, password **`remora`**,
role admin. **Anyone who is not logged in is a viewer**: they can watch, not control.

Log in with it once and change the password (account menu → **Change password**): while it is
still `remora`, the account button shows *default password!* — anyone on the network could log in
as admin. Then add your own users.

## Logging in

The account button says **Log in**. A login lasts on that device (the browser keeps it); there
is no timeout. It ends when you log out, when the password changes, with **Log out on every
device**, or when an admin deletes the account.

## Users

Admins manage accounts in **Settings → Users**: add a user (name, password, role), change a
role, set a new password (that user's logins end) or delete the account. The last admin cannot
lose the admin role or be deleted.

The accounts live in `backend/data/users.db` (SQLite; passwords are stored as scrypt hashes).
Locked out? Stop the backends and delete `users.db`: it starts again with only `remora` / `remora`.

## Settings per login

The **admin's** settings are the shared set. Viewers (no login) and the
assistant agent always see that set.

A **user** starts from the admin's values. What they change is their own:
it is stored for them in the user database (`backend/data/users.db`), and
the others still see the admin's value. Such a setting shows a **yours**
tag, and **use the admin's** drops the user's own value again. Deleting a
user deletes their settings.

Some settings are machine-wide, because the backends read them: the
camera URL and default device, the assistant settings (`assistant.*`) and
the slicer settings (`slicer.*`). Only an admin changes those; a user sees
them greyed out with "Set by the admin for everyone".

## Slicer upload

A slicer's *Send to printer* (OctoPrint upload) needs an account that may write files. In the
account menu choose **Copy API key** and paste it as the slicer's OctoPrint **API key**.
