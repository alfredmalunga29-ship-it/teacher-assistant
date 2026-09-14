// Toggles between the login and register panels.
// Called directly from the onclick="" attributes in login.html.
const wrapper = document.querySelector('.wrapper');

function registerActive() {
    wrapper.classList.add('active');
}

function loginActive() {
    wrapper.classList.remove('active');
}
