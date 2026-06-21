/** @type {import('tailwindcss').Config} */
module.exports = {
  // 'class' strategy: dark mode is toggled by adding the `dark` class to <html>,
  // controlled by the JS toggle in base.html (not the OS preference).
  darkMode: "class",
  content: [
    "./factcheck/templates/**/*.html",
    "./factcheck/static/factcheck/js/**/*.js",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
