from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.core_inquiries.services import start_or_continue_inquiry
from core.core_listings.models import Area, Complex, Unit
from core.models import Landlord, Renter, User

from . import otp
from .models import OTPCode


def make_user(username, role, phone, **extra):
    user = User.objects.create_user(
        username=username, password="pw-12345!", first_name=username.title(), last_name="Test",
        phone_number=phone, sex="female", role=role, **extra,
    )
    (Landlord if role == "landlord" else Renter).objects.create(user=user)
    return user


class TopBarTests(TestCase):
    """Dark mode switch, notification bell and profile menu."""

    def setUp(self):
        self.landlord = make_user("liza", "landlord", "09111111111", is_verified=True)
        self.renter = make_user("arem", "renter", "09222222222")
        area = Area.objects.create(area_name="Davao City")
        complex_obj = Complex.objects.create(
            landlord=self.landlord.landlord, area=area, complex_name="Sunrise", address="Poblacion",
            complex_description="x", min_price=5000, max_price=9000, status="active",
        )
        self.unit = Unit.objects.create(
            complex=complex_obj, identifier=1, bedroom_type="studio", width_dimension=4,
            length_dimension=5, furnish_level="unfurnished", max_occupant=2, price=8000,
        )

    # ---------- dark mode ----------

    def test_theme_switch_saves_on_the_account(self):
        self.client.force_login(self.renter)
        response = self.client.post(reverse("account_theme"), {"theme": "dark"})
        self.assertEqual(response.json(), {"theme": "dark"})
        self.renter.refresh_from_db()
        self.assertEqual(self.renter.theme, "dark")

        page = self.client.get(reverse("core_renters:dashboard"))
        self.assertContains(page, 'data-theme="dark"')
        self.assertContains(page, 'aria-checked="true"')

    def test_theme_switch_rejects_unknown_values_and_get(self):
        self.client.force_login(self.renter)
        self.assertEqual(self.client.post(reverse("account_theme"), {"theme": "neon"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("account_theme")).status_code, 405)
        self.renter.refresh_from_db()
        self.assertEqual(self.renter.theme, "light")

    def test_new_accounts_start_light(self):
        self.client.force_login(self.landlord)
        self.assertContains(self.client.get(reverse("core_landlords:dashboard")), 'data-theme="light"')

    def test_endpoints_need_login(self):
        for name in ("account_theme", "account_notifications_seen"):
            self.assertEqual(self.client.post(reverse(name)).status_code, 302)
        self.assertEqual(self.client.get(reverse("account_notifications")).status_code, 302)

    # ---------- bell ----------

    def test_bell_shows_new_until_opened(self):
        start_or_continue_inquiry(self.renter, "Is it still available?", unit=self.unit)
        self.client.force_login(self.landlord)

        data = self.client.get(reverse("account_notifications")).json()
        self.assertEqual(data["new_count"], 1)
        self.assertIn("New message", data["html"])
        self.assertIn("?tab=inquiries", data["html"])      # landlord's own dashboard

        self.assertEqual(self.client.post(reverse("account_notifications_seen")).status_code, 200)
        data = self.client.get(reverse("account_notifications")).json()
        self.assertEqual(data["new_count"], 0)
        self.assertIn("New message", data["html"])         # still listed, just not new

    def test_only_newer_notifications_count_after_opening(self):
        self.landlord.notifications_seen_at = timezone.now() - timedelta(hours=1)
        self.landlord.save(update_fields=["notifications_seen_at"])
        start_or_continue_inquiry(self.renter, "Hello!", unit=self.unit)
        self.client.force_login(self.landlord)
        self.assertEqual(self.client.get(reverse("account_notifications")).json()["new_count"], 1)

    def test_empty_bell(self):
        self.client.force_login(self.renter)
        data = self.client.get(reverse("account_notifications")).json()
        self.assertEqual(data["new_count"], 0)
        self.assertIn("all caught up", data["html"])

    def test_renter_links_go_to_renter_inquiries(self):
        self.client.force_login(self.renter)
        html = self.client.get(reverse("account_notifications")).json()["html"]
        self.assertNotIn("/landlords/", html)
        self.assertContains(self.client.get(reverse("core_renters:dashboard")), "/renters/dashboard/?tab=inquiries")

    # ---------- profile menu ----------

    def test_profile_menu_for_both_roles(self):
        self.client.force_login(self.renter)
        page = self.client.get(reverse("core_renters:dashboard"))
        for text in ("Arem Test", "@arem", "Renter", "Not verified", "My Profile", "Settings",
                     "Verification", "Contact Support", "mailto:", "Log Out", "data-theme-switch", "data-notif-bell"):
            self.assertContains(page, text)

        self.client.force_login(self.landlord)
        page = self.client.get(reverse("core_landlords:dashboard"))
        self.assertContains(page, "@liza")
        self.assertContains(page, "Landlord")
        self.assertContains(page, "Verified")
        self.assertNotContains(page, "Not verified")


class SignupStepTests(TestCase):
    """Sign-up in 4 steps: each Next is checked by signup/check/, Create Account opens the OTP page."""

    DATA = {
        'first_name': ' Bea ', 'last_name': 'Santos', 'phone_number': '09175550123',
        'email': 'Bea.Santos@Example.com', 'sex': 'female', 'role': 'renter',
        'password': 'Sunny-Window-42', 'confirm_password': 'Sunny-Window-42',
    }

    def setUp(self):
        patcher = mock.patch('core.core_accounts.otp.deliver')     # no SMS while testing
        self.deliver = patcher.start()
        self.addCleanup(patcher.stop)

    def check(self, step, **changes):
        return self.client.post(reverse('signup_check'), {**self.DATA, **changes, 'step': step}).json()

    def test_page_shows_four_steps_and_login_link_only_on_step_one(self):
        page = self.client.get(reverse('signup')).content.decode()
        self.assertEqual(page.count('class="signup-step"'), 4)
        for title in ("What&rsquo;s your name?", "Your contact details", "Tell us about yourself", "Create a password"):
            self.assertIn(title, page)
        step_one = page.split('data-step="2"')[0]
        self.assertIn("Already have an account?", step_one)
        self.assertEqual(page.count("Already have an account?"), 1)

    def test_each_step_passes_with_good_data(self):
        for step in (1, 2, 3, 4):
            self.assertEqual(self.check(step), {'ok': True, 'errors': {}}, step)

    def test_step_errors(self):
        self.assertIn('first_name', self.check(1, first_name='  ')['errors'])
        self.assertIn('last_name', self.check(1, last_name='123')['errors'])
        self.assertIn('phone_number', self.check(2, phone_number='0917')['errors'])
        self.assertIn('email', self.check(2, email='not-an-email')['errors'])
        self.assertEqual(set(self.check(3, sex='', role='admin')['errors']), {'sex', 'role'})
        self.assertIn('password', self.check(4, password='password', confirm_password='password')['errors'])
        self.assertIn('password', self.check(4, password='12345678901', confirm_password='12345678901')['errors'])
        self.assertIn('confirm_password', self.check(4, confirm_password='Sunny-Window-43')['errors'])

    def test_password_cant_be_like_the_name(self):
        errors = self.check(4, first_name='Bernadette', password='bernadette1', confirm_password='bernadette1')['errors']
        self.assertIn('password', errors)

    def test_phone_and_email_must_be_new(self):
        make_user('taken', 'renter', '09175550123', email='bea.santos@example.com')
        errors = self.check(2)['errors']
        self.assertIn('already registered', errors['phone_number'])
        self.assertIn('already registered', errors['email'])

    def test_unknown_step(self):
        response = self.client.post(reverse('signup_check'), {'step': '9'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(reverse('signup_check')).status_code, 405)

    def test_create_account_waits_for_the_otp(self):
        response = self.client.post(reverse('signup'), self.DATA)
        self.assertRedirects(response, reverse('otp'), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(phone_number='09175550123').exists())   # not before the OTP

        pending = self.client.session['pending_signup']
        self.assertEqual(pending['first_name'], 'Bea')
        self.assertEqual(pending['email'], 'bea.santos@example.com')
        self.assertNotIn('password', pending)
        self.assertNotIn('Sunny-Window-42', str(pending))                           # only the hash is kept

        # Back to sign-up from the OTP page: what they typed is still there (not the password)
        page = self.client.get(reverse('signup'))
        self.assertContains(page, 'value="Bea"')
        self.assertNotContains(page, 'Sunny-Window-42')

    def test_finish_signup_after_otp_creates_and_logs_in(self):
        from django.test import RequestFactory
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.contrib.messages.storage.fallback import FallbackStorage
        from .services import AccountService
        from .views import finish_signup

        self.client.post(reverse('signup'), self.DATA)
        request = RequestFactory().post('/otp/')
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.update(self.client.session.items())
        request._messages = FallbackStorage(request)

        response = finish_signup(request)
        self.assertEqual(response.url, reverse('core_renters:dashboard'))
        user = User.objects.get(phone_number='09175550123')
        self.assertTrue(user.check_password('Sunny-Window-42'))
        self.assertEqual((user.first_name, user.role), ('Bea', 'renter'))
        self.assertTrue(Renter.objects.filter(user=user).exists())
        self.assertIsNone(AccountService.pending_signup(request))                   # used up

        # A second call (no pending sign-up) goes back to the sign-up page
        self.assertEqual(finish_signup(request).url, reverse('signup'))

    def test_create_account_with_errors_reopens_the_first_bad_step(self):
        response = self.client.post(reverse('signup'), {**self.DATA, 'email': 'nope', 'confirm_password': 'x'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-start-step="2"')
        self.assertContains(response, 'Enter a valid email address.')
        self.assertContains(response, 'Passwords do not match.')
        self.assertContains(response, 'value="09175550123"')
        self.assertNotIn('pending_signup', self.client.session)



class OTPTests(TestCase):
    """core_accounts/otp.py: one-time codes by email."""

    EMAIL = 'bea@example.com'

    def setUp(self):
        patcher = mock.patch('core.core_accounts.otp.deliver')
        self.deliver = patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, email=None):
        otp.send_code(otp.Purpose.SIGNUP, email or self.EMAIL)
        return self.deliver.call_args.args[1]          # the code that was sent

    def later(self, **delta):
        return mock.patch('django.utils.timezone.now', return_value=timezone.now() + timedelta(**delta))

    def test_right_code_works_once(self):
        code = self.send()
        self.assertTrue(otp.verify_code(otp.Purpose.SIGNUP, self.EMAIL, code))
        with self.assertRaisesMessage(otp.OTPError, "request a new code"):
            otp.verify_code(otp.Purpose.SIGNUP, self.EMAIL, code)

    def test_code_is_six_digits_and_stored_hashed(self):
        code = self.send()
        self.assertRegex(code, r'^\d{6}$')
        row = OTPCode.objects.get()
        self.assertNotIn(code, row.code_hash)
        self.assertEqual((row.channel, row.target), ('email', self.EMAIL))

    def test_wrong_code_counts_down_then_locks(self):
        code = self.send()
        wrong = '000000' if code != '000000' else '111111'
        for left in (4, 3, 2, 1):
            with self.assertRaisesMessage(otp.OTPError, f"{left} tr"):
                otp.verify_code(otp.Purpose.SIGNUP, self.EMAIL, wrong)
        with self.assertRaisesMessage(otp.OTPError, "Too many wrong tries"):
            otp.verify_code(otp.Purpose.SIGNUP, self.EMAIL, wrong)
        with self.assertRaisesMessage(otp.OTPError, "Too many wrong tries"):
            otp.verify_code(otp.Purpose.SIGNUP, self.EMAIL, code)          # even the right one now

    def test_code_expires_after_five_minutes(self):
        code = self.send()
        with self.later(minutes=5, seconds=1):
            with self.assertRaisesMessage(otp.OTPError, "expired"):
                otp.verify_code(otp.Purpose.SIGNUP, self.EMAIL, code)

    def test_resend_waits_a_minute_and_only_newest_code_works(self):
        first = self.send()
        with self.assertRaisesMessage(otp.OTPError, "Please wait"):
            self.send()
        with self.later(seconds=61):
            second = self.send()
            if first != second:
                with self.assertRaises(otp.OTPError):
                    otp.verify_code(otp.Purpose.SIGNUP, self.EMAIL, first)
            self.assertTrue(otp.verify_code(otp.Purpose.SIGNUP, self.EMAIL, second))

    def test_at_most_five_codes_an_hour(self):
        for minute in range(5):
            with self.later(minutes=minute * 2):
                self.send()
        with self.later(minutes=11):
            with self.assertRaisesMessage(otp.OTPError, "Too many codes"):
                self.send()

    def test_failed_sending_doesnt_block_a_retry(self):
        self.deliver.side_effect = RuntimeError("mail server down")
        with self.assertRaisesMessage(otp.OTPError, "couldn't send"):
            self.send()
        self.assertFalse(OTPCode.objects.exists())
        self.deliver.side_effect = None
        self.send()                                     # no 60 s wait

    def test_email_is_case_insensitive(self):
        code = self.send('Bea@Example.com')
        self.assertTrue(otp.verify_code(otp.Purpose.SIGNUP, self.EMAIL, code))

    def test_mask(self):
        self.assertEqual(otp.mask('bea.santos@example.com'), 'be********@example.com')
        self.assertEqual(otp.mask('bo@example.com'), 'bo***@example.com')


class OTPEmailTests(TestCase):
    """What actually goes out: one email through settings.MAILERS."""

    def test_email(self):
        otp.deliver('bea@example.com', '123456')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['bea@example.com'])
        self.assertEqual(mail.outbox[0].subject, 'Your LookApt verification code')
        self.assertIn('123456', mail.outbox[0].body)


class OTPPageTests(TestCase):
    """Sign-up step 5: the OTP page (code by email)."""

    DATA = SignupStepTests.DATA

    def setUp(self):
        patcher = mock.patch('core.core_accounts.otp.deliver')
        self.deliver = patcher.start()
        self.addCleanup(patcher.stop)

    def sent_code(self):
        return self.deliver.call_args.args[1]

    def test_needs_a_pending_signup(self):
        self.assertRedirects(self.client.get(reverse('otp')), reverse('signup'))

    def test_create_account_emails_a_code_and_shows_the_masked_email(self):
        self.client.post(reverse('signup'), self.DATA)
        self.assertEqual(self.deliver.call_args.args[0], 'bea.santos@example.com')
        page = self.client.get(reverse('otp'))
        self.assertContains(page, 'be********@example.com')
        self.assertNotContains(page, 'SMS')

    def test_right_code_creates_the_account(self):
        self.client.post(reverse('signup'), self.DATA)
        response = self.client.post(reverse('otp'), {f'otp_{i + 1}': d for i, d in enumerate(self.sent_code())})
        self.assertRedirects(response, reverse('core_renters:dashboard'), fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(phone_number='09175550123', email='bea.santos@example.com').exists())

    def test_wrong_code_stays_on_the_page(self):
        self.client.post(reverse('signup'), self.DATA)
        wrong = '000000' if self.sent_code() != '000000' else '111111'
        response = self.client.post(reverse('otp'), {'code': wrong}, follow=True)
        self.assertContains(response, 'That code is incorrect. 4 tries left.')
        self.assertFalse(User.objects.filter(phone_number='09175550123').exists())

    def test_resend_after_a_minute(self):
        self.client.post(reverse('signup'), self.DATA)
        with mock.patch('django.utils.timezone.now', return_value=timezone.now() + timedelta(seconds=61)):
            response = self.client.post(reverse('otp_resend'), follow=True)
        self.assertContains(response, 'We sent a new code to your email.')
        self.assertEqual(self.deliver.call_count, 2)

    def test_resend_too_soon_shows_the_wait(self):
        self.client.post(reverse('signup'), self.DATA)
        response = self.client.post(reverse('otp_resend'), follow=True)
        self.assertContains(response, 'Please wait')