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
});

/* ---------- App-shell sidebar (hidden by default, opens via hamburger) ---------- */
function openSidebar() {
    const shell = document.getElementById("appShell");
    if (shell) shell.classList.add("sidebar-open");
}

function closeSidebar() {
    const shell = document.getElementById("appShell");
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