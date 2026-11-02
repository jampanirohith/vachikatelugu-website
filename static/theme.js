/* Applies the saved colour theme before first paint (loaded synchronously in <head>).
   Also decides whether the entry intro plays: home page only, once per browser session,
   not for reduced-motion users or deep links. Add ?intro to the address to replay it. */
(function () {
  var root = document.documentElement;
  var theme = "dark";
  try {
    var saved = localStorage.getItem("vachikatelugu-theme");
    if (saved === "light" || saved === "dark") theme = saved;
  } catch (error) {}
  root.setAttribute("data-theme", theme);
  root.classList.add("js");

  try {
    var path = window.location.pathname;
    var home = path === "/" || path === "/index.html";
    var forced = /[?&]intro(=1)?(&|$)/.test(window.location.search);
    var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (home && !calm && (forced || (!window.location.hash && !window.sessionStorage.getItem("vachika-intro")))) {
      root.classList.add("intro-on");
      window.sessionStorage.setItem("vachika-intro", "1");
    }
  } catch (error) {}
})();
