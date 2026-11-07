// One-time codes may be typed or pasted as "123 456" (as many authenticator apps show
// them). Keycloak only accepts "123456", so spaces are removed just before the form is
// sent. Applies to the sign-in code (#otp) and the set-up page (#totp).
document.addEventListener(
  'submit',
  function (event) {
    var fields = event.target.querySelectorAll('input[name="otp"], input[name="totp"]')
    for (var i = 0; i < fields.length; i++) {
      fields[i].value = fields[i].value.replace(/\s+/g, '')
    }
  },
  true,
)
