/**
 * NEON Torrent - Vanilla UI Interactions
 * Strictly under 5 KB. Zero external dependencies.
 */
document.addEventListener('DOMContentLoaded', function () {
  // 1. Mobile Menu Toggle
  var menuToggle = document.getElementById('menuToggle');
  var navLinks = document.getElementById('navLinks');
  if (menuToggle && navLinks) {
    menuToggle.addEventListener('click', function () {
      var isExpanded = menuToggle.getAttribute('aria-expanded') === 'true';
      menuToggle.setAttribute('aria-expanded', !isExpanded);
      navLinks.classList.toggle('show');
    });
  }

  // 2. FAQ Accordion
  var faqQuestions = document.querySelectorAll('.faq-question');
  faqQuestions.forEach(function (button) {
    button.addEventListener('click', function () {
      var item = button.closest('.faq-item');
      if (!item) return;
      var isOpen = item.classList.contains('open');

      // Close all other FAQs in the same container for clean presentation
      var siblingItems = item.parentElement.querySelectorAll('.faq-item');
      siblingItems.forEach(function (sibling) {
        if (sibling !== item) {
          sibling.classList.remove('open');
          var sibBtn = sibling.querySelector('.faq-question');
          if (sibBtn) sibBtn.setAttribute('aria-expanded', 'false');
        }
      });

      if (isOpen) {
        item.classList.remove('open');
        button.setAttribute('aria-expanded', 'false');
      } else {
        item.classList.add('open');
        button.setAttribute('aria-expanded', 'true');
      }
    });
  });

  // 3. Screenshot Gallery Tabs
  var galleryTabs = document.querySelectorAll('.gallery-tab');
  var gallerySlides = document.querySelectorAll('.gallery-slide');
  if (galleryTabs.length && gallerySlides.length) {
    galleryTabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        var targetIndex = tab.getAttribute('data-slide');
        galleryTabs.forEach(function (t) { t.classList.remove('active'); });
        gallerySlides.forEach(function (s) { s.classList.remove('active'); });

        tab.classList.add('active');
        var targetSlide = document.getElementById('slide-' + targetIndex);
        if (targetSlide) {
          targetSlide.classList.add('active');
        }
      });
    });
  }

  // 4. Pro Pricing Toggle (Yearly vs Monthly)
  var pricingToggles = document.querySelectorAll('[data-billing-toggle]');
  var proAmount = document.getElementById('proPriceAmount');
  var proPeriod = document.getElementById('proPricePeriod');
  var proBtn = document.getElementById('proCheckoutBtn');

  if (pricingToggles.length && proAmount && proPeriod && proBtn) {
    pricingToggles.forEach(function (toggle) {
      toggle.addEventListener('click', function () {
        pricingToggles.forEach(function (t) { t.classList.remove('active'); });
        toggle.classList.add('active');
        var billing = toggle.getAttribute('data-billing-toggle');
        if (billing === 'monthly') {
          proAmount.textContent = '$2.99';
          proPeriod.textContent = '/ month';
          proBtn.href = '{{CHECKOUT_PRO_MONTHLY}}';
          proBtn.textContent = 'Subscribe Monthly ($2.99/mo)';
        } else {
          proAmount.textContent = '$24.99';
          proPeriod.textContent = '/ year';
          proBtn.href = '{{CHECKOUT_PRO_YEARLY}}';
          proBtn.textContent = 'Get Pro Yearly ($24.99/yr)';
        }
      });
    });
  }
});
