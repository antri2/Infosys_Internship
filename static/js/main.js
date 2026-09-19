document.addEventListener("DOMContentLoaded", () => {
    const hamburger = document.getElementById("hamburger");
    if (hamburger) {
        hamburger.addEventListener("click", () => {
            document.body.classList.toggle("nav-open");
        });
    }
});
