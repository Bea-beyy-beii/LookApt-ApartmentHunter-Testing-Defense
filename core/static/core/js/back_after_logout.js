/* Back button after logging out: some phones (Safari) still show the page from
   memory. If the page comes back from that memory, load it again from the
   server: logged out, that sends you to the log-in page. */
window.addEventListener('pageshow', (event) => {
    if (event.persisted) window.location.reload();
});