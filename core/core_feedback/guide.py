"""
LookApt Guide (profile menu > LookApt Guide): the app's features in the order a
user meets them, from setting up the account to the end of a rental.

UserGuide is abstract; RenterGuide and LandlordGuide each give their own steps
(polymorphism), and UserGuide.for_user() picks the one for the signed-in account.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class GuideStep:
    title: str
    text: str
    where: str = ""        # where to find it in the app


class UserGuide(ABC):

    title = "LookApt Guide"
    intro = ""

    @property
    @abstractmethod
    def steps(self):
        """The journey, in order (a list of GuideStep)."""

    @staticmethod
    def for_user(user):
        guide_class = {"renter": RenterGuide, "landlord": LandlordGuide}.get(user.role)
        return guide_class() if guide_class else None


class RenterGuide(UserGuide):

    intro = "Your journey as a renter, from finding a place to moving in and beyond."

    @property
    def steps(self):
        return [
            GuideStep("Set up your account",
                      "Add a profile photo so landlords recognize you, and choose whether landlords you apply to "
                      "may see your email or phone number. Switch to dark mode any time with the sun/moon toggle.",
                      "Profile menu > My Profile / Settings"),
            GuideStep("Find a place",
                      "Browse every available listing on Home. Use the search bar and Filter by to narrow them down "
                      "by price, unit type, furnishing, amenities and more.",
                      "Home"),
            GuideStep("Explore near you",
                      "See listings on the map with nearby landmarks like schools, malls and hospitals, and set "
                      "how far you're willing to walk, commute or drive.",
                      "Find Near"),
            GuideStep("Take a closer look",
                      "Open a listing to see its photos, units, prices, amenities, nearby landmarks, reviews from "
                      "past tenants, and the landlord (look for the verified badge).",
                      "Click any listing card"),
            GuideStep("Save your favorites",
                      "Tap the heart on a listing to keep it for later.",
                      "Saved Listings"),
            GuideStep("Ask the landlord",
                      "Have a question? Press Inquire to chat with the landlord. Every conversation stays in one place.",
                      "Listing page > Inquire, then Inquiries"),
            GuideStep("Apply or join the waitlist",
                      "Apply for an available unit with your move-in date, the people moving in with you and, if you "
                      "like, a site visit. Unit taken? Join Waitlist and you'll be told when it frees up.",
                      "Unit > Apply / Join Waitlist"),
            GuideStep("Follow your requests",
                      "See if your application is pending, if your site visit is confirmed, and edit or cancel it. "
                      "The bell tells you whenever something changes.",
                      "Inquiries > Requests, and the bell"),
            GuideStep("Move in",
                      "Once the landlord approves you, your rental shows your contract and rent due dates. Rent days, "
                      "site visits and your landlord's bulletins also appear on your calendar.",
                      "Rental History and Calendar"),
            GuideStep("Leave a review",
                      "When your stay ends, rate the complex, the unit and the landlord to help the next renter.",
                      "Rental History > Leave a Review"),
            GuideStep("Stay safe",
                      "If a landlord or listing seems wrong, file a report and our team will look into it. "
                      "You can also reach us through Contact Support.",
                      "Reports Filed > File a Report"),
        ]


class LandlordGuide(UserGuide):

    intro = "Your journey as a landlord, from listing your first property to managing your tenants."

    @property
    def steps(self):
        return [
            GuideStep("Set up your account",
                      "Add a profile photo and choose whether renters may see your email or phone number on your "
                      "listings. Switch to dark mode any time with the sun/moon toggle.",
                      "Profile menu > My Profile / Settings"),
            GuideStep("Get verified",
                      "Upload a valid ID, a selfie holding it, and a business permit or proof of ownership. Until "
                      "you're verified you can prepare listings, but renters won't see them yet.",
                      "Verification pop-up / banner on your dashboard"),
            GuideStep("Add your property",
                      "Describe the complex, pin it on the map (nearby landmarks are found for you), and add photos.",
                      "My Listings > Add Property"),
            GuideStep("Add units",
                      "Add each unit's size, rent, deposit and photos. Have several similar units? Turn on Bulk "
                      "listing to create them all at once; only the unit numbers differ.",
                      "Your property > Add Unit"),
            GuideStep("Publish and keep it current",
                      "Set a property Active or Unpublished, mark units Available or Occupied, and edit or delete "
                      "listings whenever things change.",
                      "My Listings"),
            GuideStep("Talk to renters",
                      "Answer questions in chat, and review applications: confirm or decline site visits, decline "
                      "requests with a reason, or move renters to the waitlist.",
                      "Inquiries"),
            GuideStep("Approve a tenant",
                      "Approve as Tenant and set the start date. You can also assign a tenant who isn't on LookApt.",
                      "Inquiries > Requests, or Manage Rentals > Assign"),
            GuideStep("Track rent and contracts",
                      "See what's due and overdue, Mark as Paid, and renew or end contracts. Your calendar shows rent "
                      "days, contract ends and site visits; post a bulletin to tell your tenants about things like "
                      "water interruptions.",
                      "Manage Rentals and Calendar"),
            GuideStep("Watch your numbers",
                      "Your Home tab shows occupancy, what Needs Your Attention, your Monthly Receivables (Export "
                      "Financials for a PDF) and how your listings perform.",
                      "Home"),
            GuideStep("Reviews and safety",
                      "Read what tenants say in your listings' reviews. If a renter causes trouble, file a report, "
                      "or reach us through Contact Support.",
                      "Listing page > Reviews, and Reports Filed"),
        ]
