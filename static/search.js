(function () {
  var q = document.getElementById('q'), out = document.getElementById('results'), data = null;
  function norm(s) { return (s || '').toLowerCase(); }
  function render(term) {
    out.innerHTML = '';
    if (!term) return;
    var t = norm(term), hits = data.filter(function (p) {
      return norm(p.t + ' ' + p.d + ' ' + p.g + ' ' + p.c).indexOf(t) !== -1;
    }).slice(0, 40);
    if (!hits.length) { out.innerHTML = '<li>काहीही सापडले नाही.</li>'; return; }
    hits.forEach(function (p) {
      var li = document.createElement('li'), a = document.createElement('a');
      a.href = p.u; a.textContent = p.t;
      li.appendChild(a); li.appendChild(document.createTextNode(' — ' + p.c));
      out.appendChild(li);
    });
  }
  fetch(window.SEARCH_INDEX).then(function (r) { return r.json(); }).then(function (d) {
    data = d;
    var m = /[?&]q=([^&]+)/.exec(location.search);
    if (m) { q.value = decodeURIComponent(m[1].replace(/\+/g, ' ')); render(q.value); }
    q.addEventListener('input', function () { render(q.value); });
  });
})();
