# core_listings/icons.py
# Line icons (24×24, stroke = currentColor) for amenity / feature checkboxes.
from django.utils.safestring import mark_safe

FEATURE_ICONS = {
    # Unit amenities
    "air_conditioned": '<path d="M12 2v20M4.9 4.9l14.2 14.2M2 12h20M4.9 19.1 19.1 4.9"/><path d="m9 4 3 3 3-3M9 20l3-3 3 3M4 9l3 3-3 3M20 9l-3 3 3 3"/>',
    "wifi_ready": '<path d="M2 8.8a15 15 0 0 1 20 0M5 12.6a10 10 0 0 1 14 0M8.5 16.3a5 5 0 0 1 7 0"/><circle cx="12" cy="20" r="1"/>',
    "own_bathroom": '<path d="M3 12h18v2a5 5 0 0 1-5 5H8a5 5 0 0 1-5-5v-2zM6 12V5a2 2 0 0 1 4 0M7 19l-1 2M17 19l1 2"/>',
    "has_kitchen_area": '<rect x="4" y="3" width="16" height="18" rx="1.5"/><path d="M4 9h16M8 6h.01M12 6h.01M10 13h4"/>',
    "has_balcony": '<path d="M3 21h18M4 12h16M5 12v9M9 12v9M15 12v9M19 12v9M8 12V5a4 4 0 0 1 8 0v7"/>',
    "has_window_view": '<rect x="4" y="4" width="16" height="16" rx="1"/><path d="M12 4v16M4 12h16"/>',
    "own_electric_meter": '<path d="M9 2v6M15 2v6M7 8h10v4a5 5 0 0 1-10 0V8zM12 17v5"/>',
    "has_water_heater": '<path d="M4 21V9a5 5 0 0 1 9-3"/><path d="M11 9a4 4 0 0 1 8 0z"/><path d="M13 13v1M15 13v2M17 13v1"/>',

    # Complex features
    "pet_friendly": '<circle cx="5.5" cy="10" r="1.8"/><circle cx="9" cy="5.5" r="1.8"/><circle cx="15" cy="5.5" r="1.8"/><circle cx="18.5" cy="10" r="1.8"/><path d="M12 11c-3 0-5.5 4-5.5 6.5 0 1.7 1.5 2.5 3 2.5 1 0 1.6-.5 2.5-.5s1.5.5 2.5.5c1.5 0 3-.8 3-2.5C17.5 15 15 11 12 11z"/>',
    "has_parking_space": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 17V7h4a3 3 0 0 1 0 6H9"/>',
    "is_gated": '<path d="M3 21V7l9-4 9 4v14M3 11h18M7 11v10M11 11v10M15 11v10M19 11v10"/>',
    "has_laundry_area": '<rect x="4" y="2" width="16" height="20" rx="2"/><circle cx="12" cy="13" r="5"/><path d="M8 6h.01M11 6h.01"/>',
    "furnished": '<path d="M4 11V8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v3"/><path d="M2 13a2 2 0 0 1 4 0v2h12v-2a2 2 0 0 1 4 0v5H2z"/><path d="M5 18v2M19 18v2"/>',

    
    # Listing pages (renter side)
    "unit_type": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5M10 21v-6h4v6"/>',
    "area": '<path d="M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5"/>',
    "floor": '<rect x="5" y="3" width="14" height="18" rx="1"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2M11 21v-3h2v3"/>',
    "occupants": '<circle cx="9" cy="8" r="3"/><path d="M3 20c.6-3.3 2.8-5 6-5s5.4 1.7 6 5"/><path d="M16 5.5a3 3 0 0 1 0 5.5M18 15c1.6.6 2.6 2.2 3 5"/>',
    "lease": '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/>',
    "sex_restriction": '<circle cx="9" cy="10" r="4.5"/><path d="M9 14.5V21M6.5 18.5h5"/><circle cx="15.5" cy="8" r="3.5"/><path d="M18 5.5 21 2.5M18 2.5h3v3"/>',
    "units": '<rect x="4" y="3" width="16" height="18" rx="1.5"/><path d="M8 7h3M13 7h3M8 11h3M13 11h3M8 15h3M13 15h3"/>',
    "price": '<path d="M7 21V4h6a4.5 4.5 0 0 1 0 9H7M4 8h13M4 11h13"/>',
    "shield": '<path d="M12 3 4.5 6v6c0 4.5 3.2 7.8 7.5 9 4.3-1.2 7.5-4.5 7.5-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "person": '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-3.6 3.3-5.5 7-5.5s6.2 1.9 7 5.5"/>',
    "location": '<path d="M12 21s7-6.1 7-12A7 7 0 1 0 5 9c0 5.9 7 12 7 12Z"/><circle cx="12" cy="9" r="2.5"/>',
    "star": '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    "bell": '<path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
    "chat": '<path d="M5 5.5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H11l-5 3v-3.1a2 2 0 0 1-3-1.7v-8.2a2 2 0 0 1 2-2Z"/><path d="M8 10h8M8 13.5h5"/>',
    "document": '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 12h7M9 16h5"/>',
    "wallet": '<rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 10h18M16 15h2"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    "expand": '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
}


def icon_svg(name):
    return mark_safe(
        '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f'{FEATURE_ICONS.get(name, "")}</svg>'
    )