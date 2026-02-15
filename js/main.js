/* ========================================
   15歳までにみにつけた本当の学力
   Main JavaScript
   ======================================== */

document.addEventListener('DOMContentLoaded', function () {

  // --- Mobile menu toggle ---
  const menuToggle = document.querySelector('.menu-toggle');
  const mainNav = document.querySelector('.main-nav');

  if (menuToggle && mainNav) {
    menuToggle.addEventListener('click', function () {
      mainNav.classList.toggle('open');
      const expanded = mainNav.classList.contains('open');
      menuToggle.setAttribute('aria-expanded', expanded);
      menuToggle.textContent = expanded ? '\u2715' : '\u2630';
    });
  }

  // --- Scroll animation ---
  const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -40px 0px'
  };

  const observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('animate-in');
        observer.unobserve(entry.target);
      }
    });
  }, observerOptions);

  document.querySelectorAll('.pillar-card, .age-card, .article-card, .sidebar-widget').forEach(function (el) {
    el.style.opacity = '0';
    observer.observe(el);
  });

  // --- Update date display ---
  const dateEl = document.querySelector('.header-date');
  if (dateEl) {
    var now = new Date();
    var days = ['日', '月', '火', '水', '木', '金', '土'];
    var formatted = now.getFullYear() + '年'
      + (now.getMonth() + 1) + '月'
      + now.getDate() + '日'
      + '（' + days[now.getDay()] + '）';
    dateEl.textContent = formatted;
  }

  // --- Daily update counter (simulated) ---
  var dayCountEl = document.querySelector('.day-count');
  if (dayCountEl) {
    // Days since launch (placeholder: Jan 1 2026)
    var launch = new Date(2026, 0, 1);
    var now2 = new Date();
    var diff = Math.floor((now2 - launch) / (1000 * 60 * 60 * 24));
    dayCountEl.textContent = diff > 0 ? diff : 1;
  }

  // --- Smooth scroll for anchor links ---
  document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
    anchor.addEventListener('click', function (e) {
      var targetId = this.getAttribute('href');
      if (targetId === '#') return;
      var target = document.querySelector(targetId);
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

  // --- Active nav highlighting ---
  var currentPath = window.location.pathname;
  document.querySelectorAll('.main-nav a').forEach(function (link) {
    if (link.getAttribute('href') === currentPath ||
        (currentPath === '/' && link.getAttribute('href') === 'index.html') ||
        (currentPath.includes(link.getAttribute('href')) && link.getAttribute('href') !== 'index.html')) {
      link.classList.add('active');
    }
  });
});
