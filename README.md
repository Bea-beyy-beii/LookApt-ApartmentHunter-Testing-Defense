# LookApt: A Rental Search and Management System

> Looking for the perfect space shouldn't be a struggle, and neither should managing one. LookApt is a platform for landlords to post listings and manage rental business processes, and for renters to search and apply for their desired place all in one app.
---

## The Problem

Apartment hunting mostly happens through Facebook posts, group chats, word of mouth, and even physical site searching. This can cause inconvenience because:

- **Renters** can't easily find and compare places, often opting to compromise on their needs and preferences;
- **Landlords** keep track of inquiries, tenants, dues, and contract dates by hand;
- **Fake listings and scams** are common because nobody checks who is posting.

**LookApt** puts this in one place. Listings are verified and shown on a map, renters and landlords message inside the app, and tenancies are tracked from application to move-out.

---

## Key Features

| Role | What they can do |
|---|---|
| **Renter** | Search and save listings, view them on a map with nearby landmarks (schools, hospitals, etc.), apply or join a waitlist, message landlords, see rent due dates on a calendar, leave reviews, file reports |
| **Landlord** | Post complexes and units in a step-by-step form, handle inquiries and site visits, assign tenants, renew or end contracts, track monthly receivables, post bulletins to tenants, export reports to PDF |
| **Admin** | Verify landlords (AI-assisted document checks), moderate users and reports, see site activity |

**Other features:** email codes for sign-up and password reset, rate limiting on login, a light/dark theme, and a public preview for visitors who aren't signed in.

---
## OOP Concepts Used

### Classes & Objects
Classes: `User`, `Renter`, `Landlord`, `Complex`, `Unit`,
`Tenancy`, `Application`, `Conversation`, `Message`, `Review`,`OneTimeCode`, `SignUp`, `PasswordReset`, `LandlordVerification`, `LandmarkFinder`.

### Encapsulation
A class keeps its data and its rules together; the outside only calls the public methods.
- `_hash()`: the code is saved as a keyed hash, never as plain text
- `_latest()`: only the newest code works
- the rules are constants on the class: `LIFETIME` (5 min), `MAX_ATTEMPTS` (5), `RESEND_AFTER` (60 s)

- `Tenancy`: `renew()` / `end()`; the date math stays inside (`_term_end`, `_billing_stop`, `_paid_dates`)
- `Conversation`: `can_send()`, `add_message()`, `mark_read()` (nothing else touches its messages)
- `Attachment` (chat): checks the file's content, not just its name (`_is_pdf`, `_is_image`, `_is_video`), so a renamed .exe doesn't pass
- `LandlordVerification`: only `latest`, `state` and `can_submit` are shown

### Inheritance
A child class gets everything from its parent and only adds what's different.
- `User` -> `AbstractUser` (Django's built-in User class; modified to add fields like phone number and role, and to make PK into UUID
- `Renter`, `Landlord` -> `Profile` (abstract, no table of its own)
- Sign-up steps: `NameStep`, `ContactStep`, `ProfileStep`, `SecurityStep`, `TermsStep` -> `SignUpStep`
- `NewPasswordStep` -> `SecurityStep` (forgot password uses the same password rules as sign-up)
- `SignUp`, `PasswordReset` -> `EmailCodeFlow` (both wait for an emailed code)
- `CodeEmail` -> `LookAptEmail` (gets the logo and layout)
- Notifications, more than one level: `Notification` -> `VerificationNotice` -> `Verified` / `VerificationRejected` / `NewDocumentsNeeded`

### Abstraction
An abstract class (`ABC` + `@abstractmethod`) says *what* a child must do, not *how*.
Child classes provide their own implementation of their parent classes' abstract method declaration.
- `SignUpStep._check()`: each step's own rules
- `EmailCodeFlow.email` / `.name`: where the code goes and who to greet
- `MessageSender._thread()`: which conversation a message goes to
- `Geocoder.search()`, `LandmarkSource.fetch()`: anything that finds places on the map
- `DashboardSection.context()`, `LookAptEmail.text()`, `AttentionCheck`, `UploadCheck`

### Polymorphism
Same method call, different class, different result.
- **Sign-up:** `SignUpForm` loops over the 5 steps and calls `.clean()`; each step runs its own `_check()`
- **Maps:** `OverpassProvider`, `LocalProvider`, `PhotonGeocoder`, `NominatimGeocoder` can be swapped for each other;
  `LandmarkFinder` uses saved landmarks in the database + live OpenStreetMap, and only the saved ones when OSM is down
- **Verification:** `Attachment.for_file()` -> `ImageAttachment` or `PdfAttachment`; each makes its own `block()` for Claude
- **Messaging:** `RenterInquiry`, `LandlordMessage`, `ThreadReply` all `send()`, but each one decides who may write and which thread it goes to
- **Roles:** found without `if role == ...`

- **Calendar:** Calendar.class_for(user)       -> LandlordCalendar / RenterCalendar
- **Notifications:** NotificationFeed.for_user(user) -> LandlordNotifications / RenterNotifications

- `Landlord` overrides `Profile.rating` (only landlords get stars)

### Composition
An object made from other objects ("has a" instead of "is a").
- `EmailCodeFlow` has a `OneTimeCode`
- `AIReader` builds `Attachment` objects
- `LandmarkFinder` uses the map providers
- `MessageSender` uses `Attachment` and `Conversation`

### Multiple Inheritance / Mixins
- `OverpassProvider(OpenStreetMapClient, LandmarkSource)`: shared HTTP + caching, plus the interface
- `LocalProvider(LandmarkSource, Geocoder)`: one class, both jobs
- `Welcome(RoleBased, Notification)`: a notification that knows the roles
- Views stack mixins: `SignUpView(RateLimitMixin, LegalContextMixin, SignUpFlowMixin, TemplateView)`
---

## Tech Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3.14.7 |
| **Framework** | Django 6.1 |
| **Database** | PostgreSQL (hosted on Supabase) via `psycopg2` |
| **Frontend** | Django templates, HTML, CSS and JavaScript |
| **File storage** | AWS S3 (`boto3`, `django-storages`) for listing photos and verification documents |
| **Maps** | Folium for the map, OpenStreetMap (Overpass, Photon, Nominatim) for landmarks and search, Google Maps API |
| **AI** | Anthropic Claude API reads landlord ID and permit documents for verification |
| **PDF reports** | ReportLab |
| **Email** | SMTP (verification codes, password reset, notifications) |
| **Deployment** | Gunicorn and WhiteNoise, on Render |
| **Config** | `django-environ` (`.env` file) |
| **Testing** | Django's test framework (`TestCase`) |

---

## Project Structure

```
LookApt/            # Django project settings & root URLs
core/
├── core_accounts/      # sign-up, login, password reset
├── core_listings/      # complexes, units, listing wizard, saved listings
├── core_maps/          # map view, landmarks, geocoding providers
├── core_inquiries/     # applications, waitlist, chat, notifications
├── core_rentals/       # tenant assignment, rent, renewals
├── core_calendar/      # rent due dates, site visits, bulletins
├── core_reviews/       # ratings and reviews
├── core_reports/       # user reports
├── core_verification/  # landlord document verification (AI-assisted)
├── core_landlords/     # landlord dashboard, receivables, PDF export
├── core_renters/       # renter dashboard
├── core_admin/         # admin panel & moderation
├── core_preview/       # public landing page / preview
├── core_feedback/      # feedback & user guide
├── roles.py            # RoleBased: role → subclass lookup (polymorphism)
└── sections.py         # DashboardSection: abstract dashboard building block
Users.py, Main.py       # early OOP prototype of the User class
```
