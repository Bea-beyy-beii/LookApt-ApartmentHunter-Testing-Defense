# How LookApt uses Object-Oriented Programming

LookApt is a Django app. Django is itself object-oriented (every table is a
class, every page can be a class), and the app's own logic is written the same
way: **every business rule lives in a class**. Pages are class-based views,
data rules are model methods and custom QuerySets, and each workflow is an
object that keeps its own state.

This page points to the clearest example of each OOP idea.

---

## 1. Classes and objects

| Class | File | What one object represents |
|---|---|---|
| `User`, `Renter`, `Landlord` | `core/models.py` | an account and its role profile |
| `Complex`, `Unit`, `SavedListing` | `core/core_listings/models.py` | an apartment complex, one unit, a saved listing |
| `Tenancy` | `core/core_rentals/models.py` | one renter living in one unit |
| `Application`, `Conversation`, `Message` | `core/core_inquiries/models.py` | a rental request, a chat thread, a message |
| `ReceivablesReport(user, month)` | `core/core_landlords/services.py` | one landlord's money report for one month |
| `PasswordReset(request)` / `SignUp(request)` | `core/core_accounts/services.py` | one visitor's reset / sign-up in progress |
| `GeoPoint`, `TravelMode` | `core/core_maps/maps/geo.py` | a map coordinate, a way of travelling |
| `Month` | `core/core_landlords/services.py` | a calendar month (a value object) |

Service classes are **built with the data they work on** and their methods use
`self`. For example, `ReceivablesReport(user, month).as_dict()` and
`TenantAssignment.create(...).save()`.

## 2. Encapsulation (data and behaviour together, internals hidden)

- **Objects act on themselves.**
  - A tenancy ends itself: `tenancy.end(...)`, `tenancy.renew()`, `tenancy.mark_paid(...)`.
  - It also answers about itself: `tenancy.payment_status`, `tenancy.due_dates(...)` (`core_rentals/models.py`).
  - An application changes its own state: `application.close()`, `application.move_to_waitlist()` (`core_inquiries/models.py`).
  - A verification request decides itself: `request.approve()`, `request.reject()` (`core_verification/models.py`).
- **Queries live in custom QuerySets.**
  - `Complex.objects.renter_visible()`, `Unit.objects.for_renters()` (`core_listings/models.py`)
  - `Tenancy.objects.active()` (`core_rentals/models.py`)
  - `Review.objects.for_complex(c).summary("complex")` (`core_reviews/models.py`)
  - `Application.objects.visible_to(user)` (`core_inquiries/managers.py`)
- **Private helpers and properties.**
  - Helpers start with `_`: `Tenancy._term_end()`, `OneTimeCode._hash()`, `LocationMap._add_landmarks()`.
  - Computed values are `@property`: `User.display_name`, `Tenancy.lease_months`, `ListingSearch.filter_count`.
- **Constants belong to their class.**
  - `Tenancy.ENDING_SOON_DAYS`, `PasswordReset.WINDOW`, `BulkUnitForm.MAX_UNITS`, `OneTimeCode.MAX_ATTEMPTS`.

## 3. Inheritance (reuse a parent, add or change what differs)

| Parent | Children | File |
|---|---|---|
| `Profile` (abstract model) | `Renter`, `Landlord` | `core/models.py` |
| `Listing` (abstract model) | `Complex`, `Unit` | `core_listings/models.py` |
| `ListingPicture` (abstract model) | `ComplexPicture`, `UnitPicture` | `core_listings/models.py` |
| `ListingForm` | `ComplexForm`, `UnitForm` → `BulkUnitForm` | `core_listings/forms.py` |
| `ListingWizardView` | `PropertyWizardView` → `PropertyCreateView` / `PropertyEditView`, `UnitWizardView` → `UnitCreateView` / `UnitEditView` | `core_listings/views.py` |
| `RoleRequiredMixin` | `RenterRequiredMixin`, `LandlordRequiredMixin`, `AdminRequiredMixin` | `core_accounts/mixins.py` |
| `SecurityStep` | `NewPasswordStep` (sign-up's password rules + "not your current password") | `core_accounts/services.py` |
| `ListTab` | `StatusListTab` → `VerificationTab`, `ReportsTab`; `UsersTab`; `FeedbackTab` | `core_admin/tabs.py` |
| `UserGuide` | `RenterGuide`, `LandlordGuide` | `core_feedback/guide.py` |
| `CloseRequest` | `RejectRequest`, `CancelRequest` | `core_inquiries/workflow.py` |
| `OpenStreetMapClient` | `OverpassProvider`, `PhotonGeocoder`, `NominatimGeocoder` | `core_maps/maps/providers.py` |
| `MarkerStyle` | `CategoryStyle` | `core_maps/maps/categories.py` |

Every page is a **class-based view** that inherits from Django's `View`,
`TemplateView` or `FormView`, plus the mixins above.

## 4. Abstraction (abstract base classes: say *what*, not *how*)

Each of these declares methods with `@abstractmethod` (Python's `abc` module);
a subclass must implement them before it can be used.

| Abstract class | Must implement | File |
|---|---|---|
| `DashboardSection` | `context()` | `core/sections.py` |
| `Geocoder` / `LandmarkSource` | `search()` / `fetch()` | `core_maps/maps/providers.py` |
| `JsonApiView` | `payload()` | `core_maps/views.py` |
| `SignUpStep` | `_check()` | `core_accounts/services.py` |
| `EmailCodeFlow` | `email`, `name` | `core_accounts/services.py` |
| `LookAptEmail` | `text`, `html_context` | `core_accounts/emails.py` |
| `Notification` | `subject`, `paragraphs` | `core_admin/notify.py` |
| `ListTab` | `_results()` | `core_admin/tabs.py` |
| `AdminDetailView` | `get_object()`, `show()`, `act()` | `core_admin/views.py` |
| `Reporter` | `_links()` | `core_reports/services.py` |
| `Calendar` | `_events()`, `_tenancies()` ... | `core_calendar/services.py` |
| `MessageSender` | `_check_allowed()`, `_thread()` | `core_inquiries/services.py` |
| `NotificationFeed` | `_application_item()` | `core_inquiries/services.py` |
| `RequestAction` | `_apply()` | `core_inquiries/workflow.py` |
| `TenantAssignment` | `_tenant()` | `core_rentals/services.py` |
| `RentalActionView` | `perform()` | `core_rentals/views.py` |
| `AttentionCheck` | `item()` | `core_landlords/services.py` |
| `UploadCheck` | the file checks | `core_listings/forms.py` |
| `ListingPage` | `_queryset()`, `context()` | `core_listings/detail_services.py` |
| `Attachment` | how a file is sent to the AI | `core_verification/extractors/ai_reader.py` |
| `PreviewView` | `preview_context()` | `core_preview/views.py` |
| `UserGuide` | `steps` | `core_feedback/guide.py` |
| `ColorRole` | `dark()` | `core/management/commands/build_dark_theme.py` |

Many of these use the **template method** pattern. The parent's method runs
the fixed steps, and each subclass fills in only the step that differs:
- `RequestAction.run()` checks the status, calls `_apply()`, then gives the message.
- `MessageSender.send()`, `Notification.send()` and `AdminDetailView.post()` work the same way.

## 5. Polymorphism (same call, different behaviour)

The code calls the same method on different classes, so it never has to check
`if role == ...` or `if kind == ...`.

- **Dashboards.**
  - The landlord `DashboardView` lists `InquiriesSection`, `ReportsSection`, `ListingsSection`, `RentalsSection`, `HomeSection` and `VerificationSection`.
  - `SectionedDashboardMixin` just calls `.context()` on each one (`core/sections.py`, `core_landlords/views.py`, `core_renters/views.py`).
- **Roles.**
  - `Reporter.for_user(user)` gives a `RenterReporter` or a `LandlordReporter`, each with its own categories and targets.
  - The same for `Calendar.for_user()` (`LandlordCalendar` / `RenterCalendar`) and `NotificationFeed.for_user()` (`LandlordNotifications` / `RenterNotifications`).
  - `user.home_url_name` asks the user's `Profile` subclass where to go.
- **Map providers.**
  - `PlaceSearch` tries each `Geocoder` (`PhotonGeocoder`, `NominatimGeocoder`, `LocalProvider`) with the same `.search()` call.
  - Landmarks come from any `LandmarkSource` through `.fetch()`.
- **Messages to users.**
  - `Welcome.for_user(user).send()` picks `LandlordWelcome` or `RenterWelcome`.
  - Every notice (`Verified`, `Suspended`, `ReportUpdated` ...) is sent with the same `.send()`.
- **LookApt Guide.**
  - `UserGuide.for_user(user)` gives a `RenterGuide` or a `LandlordGuide`, and the pop-up just shows its `.steps`.
- **Forms.**
  - `form.save_listing()` saves one complex, one unit, or (for `BulkUnitForm`) many units.
- **Sign-up steps.**
  - `SignUpForm.STEPS[n](data).clean()` checks the step without an `if step == ...` chain.
- **"Needs Your Attention".**
  - The Home tab loops over `OverdueRent`, `PendingRequests`, `SiteVisitsToConfirm`, `ContractsEndingSoon` and `VacantWithWaitlist`, calling `.item()` on each.
- **Overriding Django's own methods.**
  - `User.save()`, `Form.clean_*()`, `View.get()` / `post()`, `get_context_data()`, and `dispatch()` in `RoleRequiredMixin`.

## 6. Composition (objects made of objects)

- **Profiles.** A `Renter` and a `Landlord` each *have a* `User`.
- **Listings.** A `Complex` *has* `Unit`s and pictures; a `Tenancy` *has* a `Unit` and a `Renter`.
- **Dashboards.** A dashboard view *has* a list of section objects.
- **Inquiries tab.** `InquiriesSection` is built from an `Inbox`, a `RequestTabs` and a `NotificationFeed`.

---

## What is still a plain function, and why

- **Django template tags and filters.** These are the `@register` functions in `templatetags/`, and Django requires them to be functions. Each one only calls a class, for example `star_rating` → `StarRating`.
- **Upload-path functions.** `avatar_path`, `document_path` and `verification_storage` are referenced by the database migrations by name, so they must stay where they are.
- **`today()` and the small date/size formatters in `core_inquiries/labels.py`.** These are stateless one-line utilities. The tests also replace `today()` to pretend it is a different day.
