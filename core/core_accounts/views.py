from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from core.core_inquiries.services import notifications_for
from .services import AccountService


ROLE_HOME = {
    'renter': 'core_renters:dashboard',
    'landlord': 'core_landlords:dashboard',
    'admin': 'admin:index',
}

def signup_view(request):
    if request.method == 'POST':
        d = request.POST
        form_data = {
            'first_name': d.get('first_name', ''),
            'last_name': d.get('last_name', ''),
            'phone_number': d.get('phone_number', ''),
            'email': d.get('email', ''),
            'sex': d.get('sex', ''),
            'role': d.get('role', ''),
        }
        if d.get('password') != d.get('confirm_password'):
            messages.error(request, "Passwords do not match.")
            return render(request, 'core_accounts/signup.html', {'form_data': form_data})
        try:
            user = AccountService.register(
                form_data['first_name'], form_data['last_name'],
                form_data['phone_number'], form_data['email'],
                form_data['sex'], form_data['role'], d.get('password', ''),
            )
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
            return render(request, 'core_accounts/signup.html', {'form_data': form_data})
        login(request, user)
        return redirect(ROLE_HOME[user.role])
    return render(request, 'core_accounts/signup.html')

def login_view(request):
    if request.method == 'POST':
        user = authenticate(
            request,
            username=request.POST.get('identifier', ''),
            password=request.POST.get('password', ''),
        )
        if user:
            login(request, user)
            return redirect(ROLE_HOME[user.role])
        messages.error(request, "Invalid phone/username or password.")
    return render(request, 'core_accounts/login.html')

def logout_view(request):
    # Ends the session (the sidebar "Log Out" link used to only open the login page)
    logout(request)
    return redirect('login')

def otp_view(request):
    return render(request, 'core_accounts/otp.html')


# ------------------------------------------------------------------ TOP BAR (dark mode switch + bell)

@login_required
@require_POST
def theme_view(request):
    """Dark mode switch: saves 'light' / 'dark' on the account."""
    theme = request.POST.get('theme', '')
    if theme not in dict(request.user.THEME_CHOICES):
        return JsonResponse({'error': 'Unknown theme.'}, status=400)
    request.user.theme = theme
    request.user.save(update_fields=['theme'])
    return JsonResponse({'theme': theme})


@login_required
@require_GET
def notifications_view(request):
    """The bell's dropdown list (rendered HTML) + how many arrived since it was last opened."""
    items = notifications_for(request.user)
    html = render_to_string('core_accounts/partials/notification_items.html',
                            {'notifications': items[:5]}, request=request)
    return JsonResponse({'html': html, 'new_count': sum(1 for n in items if n['is_new'])})


@login_required
@require_POST
def notifications_seen_view(request):
    """Opening the bell clears its red dot."""
    request.user.notifications_seen_at = timezone.now()
    request.user.save(update_fields=['notifications_seen_at'])
    return JsonResponse({'new_count': 0})