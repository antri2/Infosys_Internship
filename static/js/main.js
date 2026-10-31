document.addEventListener("DOMContentLoaded", () => {
    const hamburger = document.getElementById("hamburger");
    if (hamburger) {
        hamburger.addEventListener("click", () => {
            document.body.classList.toggle("nav-open");
        });
    }

    // Close the profile dropdown / sidebar when clicking anywhere else on the page.
    document.addEventListener("click", (event) => {
        const dropdown = document.getElementById("profileDropdown");
        const menuButton = event.target.closest(".topbar-user");
        if (dropdown && dropdown.classList.contains("open") && !menuButton) {
            dropdown.classList.remove("open");
        }
    });

    // Esc key closes the sidebar too, since it's an off-canvas overlay.
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeSidebar();
    });

    // Restore the persisted collapsed/expanded state after paint so the
    // sidebar does not visibly jump from expanded to collapsed on load.
    restoreSidebar();
});

/* ---------- App-shell sidebar ---------- */
/* Two persistent states rather than show/hide:
     expanded   -> .sidebar-open absent, width 272px, labels visible
     collapsed  -> .sidebar-collapsed, width 78px, icon only + hover tooltip
   Below 900px CSS reverts the sidebar to an overlay, where .sidebar-open is
   what slides it in, so both classes can coexist with the responsive rules. */
const SIDEBAR_KEY = "careerai:sidebar-collapsed";

function shellElement() {
    return document.getElementById("appShell");
}

function applySidebar(collapsed, persist) {
    const shell = shellElement();
    if (!shell) return;

    shell.classList.toggle("sidebar-collapsed", collapsed);
    // Mirror onto <html> too, so the CSS that only reacts to the <html> class
    // (the pre-paint state) stays consistent with the shell.
    document.documentElement.classList.toggle("sidebar-collapsed", collapsed);

    const button = document.getElementById("sidebarCollapse");
    if (button) {
        button.setAttribute("aria-expanded", collapsed ? "false" : "true");
        button.setAttribute(
            "aria-label",
            collapsed ? "Expand sidebar" : "Collapse sidebar"
        );
        button.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
    }

    if (persist) {
        try {
            localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
        } catch (error) {
            /* Private browsing: the choice simply does not persist. */
        }
    }
}

function toggleSidebar() {
    const shell = shellElement();
    if (!shell) return;
    applySidebar(!shell.classList.contains("sidebar-collapsed"), true);
}

function restoreSidebar() {
    // <html> already carries the class from the inline <head> script, so the
    // first paint was correct. Adopt it here rather than re-reading and
    // re-applying, which is what produced the visible open-then-close flicker.
    const preSet = document.documentElement.classList.contains("sidebar-collapsed");
    applySidebar(preSet, false);
}

/* ------------------------------------------------------------------ *
 * Compact toast
 * ------------------------------------------------------------------
 * Save/Apply used a blocking window.alert(), which covered the page and could
 * not be styled. These are non-blocking, anchored so they never overlap a
 * card, and they carry the real status the endpoint returned -- a request that
 * failed is shown as an error, never as a success.
 */
function showToast(message, kind, options) {
    const opts = options || {};
    let host = document.getElementById("careerai-toast-host");
    if (!host) {
        host = document.createElement("div");
        host.id = "careerai-toast-host";
        host.className = "toast-host";
        host.setAttribute("aria-live", "polite");
        host.setAttribute("aria-atomic", "false");
        document.body.appendChild(host);
    }

    const toast = document.createElement("div");
    toast.className = "toast toast--" + (kind === "error" ? "error" : "success");
    toast.setAttribute("role", kind === "error" ? "alert" : "status");

    const text = document.createElement("span");
    text.className = "toast__text";
    text.textContent = message;
    toast.appendChild(text);

    const close = document.createElement("button");
    close.type = "button";
    close.className = "toast__close";
    close.setAttribute("aria-label", "Dismiss");
    close.textContent = "×";
    close.addEventListener("click", function () { remove(); });
    toast.appendChild(close);

    host.appendChild(toast);
    // Next frame so the entry transition runs from the hidden state.
    requestAnimationFrame(function () { toast.classList.add("is-visible"); });

    let removed = false;
    function remove() {
        if (removed) return;
        removed = true;
        toast.classList.remove("is-visible");
        setTimeout(function () {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 200);
    }

    setTimeout(remove, opts.duration || (kind === "error" ? 6000 : 3500));
    return toast;
}

window.showToast = showToast;

/* Kept for the mobile overlay path (the hamburger in the topbar). */
function openSidebar() {
    const shell = shellElement();
    if (shell) shell.classList.add("sidebar-open");
}

function closeSidebar() {
    const shell = shellElement();
    if (shell) shell.classList.remove("sidebar-open");
}


/* ---------- Topbar profile dropdown ---------- */
function toggleProfileMenu(event) {
    event.stopPropagation();
    const dropdown = document.getElementById("profileDropdown");
    if (dropdown) dropdown.classList.toggle("open");
}

/* ---------- Profile page: inline add/edit forms ---------- */
function toggleForm(id) {
    const el = document.getElementById(id);
    if (el) el.classList.toggle("open");
}