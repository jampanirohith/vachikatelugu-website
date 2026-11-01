/* Applies the saved colour theme before first paint (loaded synchronously in <head>). */
(function () {
  var theme = "dark";
  try {
    var saved = localStorage.getItem("vachikatelugu-theme");
    if (saved === "light" || saved === "dark") theme = saved;
  } catch (error) {}
  document.documentElement.setAttribute("data-theme", theme);
  document.documentElement.classList.add("js");
})();
