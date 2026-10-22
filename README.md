# LookApt — Apartment Hunter

> Your next home, in a tap.

LookApt is a web app for renting apartments in **Davao City**. Renters search listings on a map, check what's nearby and apply for units. Landlords post their properties, manage tenants and track rent from one dashboard. Admins verify landlords and handle reports.

---

## The Problem

Apartment hunting in Davao City mostly happens through Facebook posts, group chats and word of mouth:

- **Renters** can't easily compare places, see where they are, or tell whether a landlord is real.
- **Landlords** keep track of inquiries, tenants, rent and contract dates by hand.
- **Fake listings and scams** are common because nobody checks who is posting.

**LookApt** puts this in one place. Listings are verified and shown on a map, renters and landlords message inside the app, and tenancies are tracked from application to move-out.

---

## Key Features

| Role | What they can do |
|---|---|
| **Renter** | Search and save listings, view them on a map with nearby landmarks (schools, hospitals, etc.), apply or join a waitlist, message landlords, see rent due dates on a calendar, leave reviews, file reports |
| **Landlord** | Post complexes and units in a step-by-step form, handle inquiries and site visits, assign tenants, renew or end contracts, track monthly receivables, post bulletins to tenants, export reports to PDF |
| **Admin** | Verify landlords (AI-assisted document checks), moderate users and reports, see site activity |

**Other features:** email codes for sign-up and password reset, rate limiting on login, sign-up and search, a light/dark theme, and a public preview for visitors who aren't signed in.

---

## OOP Concepts Used

| Concept | Where it shows up in LookApt |
|---|---|
| **Classes & Objects** | Each real-world thing is a class: `User`, `Renter`, `Landlord`, `Complex`, `Unit`, `Tenancy`, `Review`, `Application`. The first prototype (`Users.py`, `Main.py`) models a user with `logIn()`, `logOut()` and `display_user_info()`. |
| **Encapsulation** | Each object keeps its data and rules together. `Tenancy` has `renew()` and `end()` and hides its date logic in private helpers (`_term_end`, `_billing_stop`, `_paid_dates`). Services like `SignUp`, `PasswordReset` and `TenantAssignment` keep each process in one class. |
| **Inheritance** | `Renter` and `Landlord` inherit from an abstract `Profile`. `RentalsSection` and `RenterRentalsSection` extend `TenancySection`. Views build on Django's `TemplateView`/`View` and add mixins such as `LandlordRequiredMixin` and `RateLimitMixin`. |
| **Abstraction** | Abstract base classes (`ABC` + `@abstractmethod`) define what a class must do, not how: `DashboardSection.context()`, `Geocoder.search()`, `LandmarkSource.fetch()`, `AttentionCheck`, `UploadCheck`, `Middleware`. |
| **Polymorphism** | `RoleBased.class_for(user)` picks the right subclass for a role (such as `LandlordCalendar` or `RenterCalendar`) without `if role == ...` checks. Dashboards loop over sections and call `.context()` on each one. Map providers (`OverpassProvider`, `PhotonGeocoder`, `NominatimGeocoder`, `LocalProvider`) can stand in for each other. `Landlord` overrides `Profile.rating`. |
| **Multiple Inheritance / Mixins** | `OverpassProvider(OpenStreetMapClient, LandmarkSource)` combines shared HTTP and caching code with an interface. `SectionedDashboardMixin` adds sectioned dashboards to any view. |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3 |
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
Users.py, Main.py   # early OOP prototype of the User class
```
