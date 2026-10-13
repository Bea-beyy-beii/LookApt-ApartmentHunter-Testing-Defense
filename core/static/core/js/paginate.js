// =========================================================
// Pages for a grid of listing cards (renter Home: 9 per page,
// Saved Listings: 8). Only the cards change; the rest of the tab stays.
//
//   <section data-paginate="9" data-pager="#home-pager"> ...cards... </section>
//   <nav class="pager" id="home-pager" hidden></nav>
//
// The cards are all in the page already (the search in renter_search.js
// swaps them); this just shows one page of them. It re-counts by itself when
// cards are added or removed (saving / unsaving, a new search).
// =========================================================

(function () {

    const CARD = "[data-listing-card]";

    class Paginator {

        constructor(grid) {
            this.grid = grid;
            this.perPage = Number(grid.dataset.paginate) || 9;
            this.nav = document.querySelector(grid.dataset.pager);
            this.page = 1;

            this.nav.addEventListener("click", event => {
                const button = event.target.closest("button[data-page]");
                if (button && !button.disabled) this.go(Number(button.dataset.page), true);
            });

            // Cards added / removed: show the page again. A whole new set of
            // cards (a new search) starts from page 1.
            new MutationObserver(records => {
                const replaced = records.some(record => record.removedNodes.length > 1 || record.addedNodes.length > 1);
                if (replaced) this.page = 1;
                this.render();
            }).observe(grid, { childList: true });

            this.render();
        }

        cards() {
            return [...this.grid.children].filter(child => child.matches(CARD));
        }

        pageCount() {
            return Math.max(1, Math.ceil(this.cards().length / this.perPage));
        }

        go(page, scroll) {
            this.page = Math.min(Math.max(1, page), this.pageCount());
            this.render();
            if (scroll) {
                // Back to the first row of cards (the header and the rest stay put)
                const top = this.grid.getBoundingClientRect().top;
                if (top < 0) this.grid.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        }

        render() {
            const cards = this.cards();
            const pages = this.pageCount();
            this.page = Math.min(this.page, pages);
            const first = (this.page - 1) * this.perPage;

            cards.forEach((card, index) => {
                card.classList.toggle("is-paged-out", index < first || index >= first + this.perPage);
            });

            this.nav.hidden = pages <= 1;
            if (pages > 1) this.nav.replaceChildren(...this.buttons(pages));
        }

        // ‹  1  2  3 … 9  ›
        buttons(pages) {
            const make = (label, page, { current = false, disabled = false, aria } = {}) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "pager-btn";
                button.textContent = label;
                button.dataset.page = page;
                button.disabled = disabled;
                if (aria) button.setAttribute("aria-label", aria);
                if (current) {
                    button.classList.add("is-current");
                    button.setAttribute("aria-current", "page");
                }
                return button;
            };

            const items = [make("‹", this.page - 1, { disabled: this.page === 1, aria: "Previous page" })];
            let last = 0;
            for (let page = 1; page <= pages; page++) {
                // First, last, and the ones next to the current page
                if (page !== 1 && page !== pages && Math.abs(page - this.page) > 1) continue;
                if (page - last > 1) {
                    const gap = document.createElement("span");
                    gap.className = "pager-gap";
                    gap.textContent = "…";
                    items.push(gap);
                }
                items.push(make(String(page), page, { current: page === this.page, aria: `Page ${page}` }));
                last = page;
            }
            items.push(make("›", this.page + 1, { disabled: this.page === pages, aria: "Next page" }));
            return items;
        }
    }

    function init() {
        document.querySelectorAll("[data-paginate]").forEach(grid => {
            if (!grid.paginator) grid.paginator = new Paginator(grid);
        });
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();

})();
