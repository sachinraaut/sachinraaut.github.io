/* Client-side search over /search.json. No library: the index is small and stays that way for years. */
(function () {
  var q = document.getElementById('q'), out = document.getElementById('results'),
      count = document.getElementById('count'), data = null, timer = null;

  function norm(s) { return (s || '').toLowerCase().trim(); }

  /* Title hits matter most, then tags, then the summary. Every word of the query must appear somewhere. */
  function score(p, words) {
    var t = norm(p.t), g = norm(p.g), d = norm(p.d), c = norm(p.c), s = 0;
    for (var i = 0; i < words.length; i++) {
      var w = words[i], hit = 0;
      if (t.indexOf(w) !== -1) hit += 10;
      if (g.indexOf(w) !== -1) hit += 5;
      if (c.indexOf(w) !== -1) hit += 3;
      if (d.indexOf(w) !== -1) hit += 2;
      if (!hit) return 0;
      s += hit;
    }
    if (t.indexOf(words.join(' ')) === 0) s += 8;
    return s;
  }

  function render(term) {
    out.innerHTML = '';
    var words = norm(term).split(/\s+/).filter(Boolean);
    if (!words.length) { count.textContent = ''; return; }
    var hits = data.map(function (p) { return { p: p, s: score(p, words) }; })
                   .filter(function (x) { return x.s > 0; })
                   .sort(function (a, b) { return b.s - a.s || (a.p.y < b.p.y ? 1 : -1); })
                   .slice(0, 40);
    if (!hits.length) {
      count.textContent = '';
      out.innerHTML = '<li>काहीही सापडले नाही. दुसऱ्या शब्दांनी शोधून पाहा.</li>';
      return;
    }
    count.textContent = hits.length + ' लेख सापडले';
    hits.forEach(function (x) {
      var li = document.createElement('li'), a = document.createElement('a'), c = document.createElement('span');
      a.href = x.p.u; a.textContent = x.p.t;
      c.className = 'chip c-' + x.p.s; c.textContent = x.p.c;
      li.appendChild(a); li.appendChild(c);
      out.appendChild(li);
    });
  }

  fetch(window.SEARCH_INDEX).then(function (r) { return r.json(); }).then(function (d) {
    data = d;
    var m = /[?&]q=([^&]+)/.exec(location.search);
    if (m) { q.value = decodeURIComponent(m[1].replace(/\+/g, ' ')); render(q.value); }
    q.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () { render(q.value); }, 120);
    });
  }).catch(function () { out.innerHTML = '<li>शोध सध्या उपलब्ध नाही.</li>'; });
})();
