const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const script = fs.readFileSync(path.join(__dirname, 'script.js'), 'utf8');
const technicalCopy = /\b(?:Godot|Python|OSM|OpenStreetMap|NPC|HUD|API|FMI|Digitraffic)\b|renderö|karttaruut|reitinhaun palautuminen|spawn clearances|map layers|cached data/i;
const section = id => html.split(`id="${id}"`)[1].split('</section>')[0];
const counts = {
  '.hero-meta span': 3,
  '.screenshot-grid figure': (html.match(/<figure>/g) || []).length,
  'nav a': (html.split('</nav>')[0].match(/<a /g) || []).length - 1, // exclude the brand
  '.control-row span': (section('how-to-play').match(/class="control-row"/g) || []).length,
  '#features .feature-card': (section('features').match(/<article /g) || []).length,
  '#roadmap .feature-card': (section('roadmap').match(/<article /g) || []).length,
  '#release-notes .notes-list li': (section('release-notes').match(/<li>/g) || []).length,
};

function element() {
  const children = new Map();
  return {
    textContent: '', innerHTML: '', lastChild: {}, firstChild: {}, listeners: {},
    querySelector(selector) {
      if (!children.has(selector)) children.set(selector, element());
      return children.get(selector);
    },
    setAttribute(name, value) { this[name] = value; },
    addEventListener(name, callback) { this.listeners[name] = callback; },
  };
}

for (const language of ['fi', 'en']) {
  test(`${language}: all HTML rows translate and the language toggle works`, () => {
    const nodes = new Map();
    const lists = new Map(Object.entries(counts).map(([key, n]) => [key, Array.from({ length: n }, element)]));
    const document = {
      documentElement: {},
      querySelector(selector) {
        if (!nodes.has(selector)) nodes.set(selector, element());
        return nodes.get(selector);
      },
      querySelectorAll(selector) {
        assert(lists.has(selector), `Unexpected list selector: ${selector}`);
        return lists.get(selector);
      },
    };
    const context = vm.createContext({ document, navigator: { languages: [language] } });
    vm.runInContext(script, context); // exercises the complete startup, not just the translation data
    for (let toggle = 0; toggle < 3; toggle++) {
      const current = document.documentElement.lang;
      const t = vm.runInContext(`translations.${current}`, context);
      const other = vm.runInContext(`translations.${current === 'fi' ? 'en' : 'fi'}`, context);
      assert.deepEqual(Object.keys(t).sort(), Object.keys(other).sort());
      for (const key of ['features', 'notes', 'controls']) {
        assert.equal(t[key].length, other[key].length, key);
        t[key].forEach((entry, i) => {
          assert.deepEqual(JSON.stringify(entry).match(/\d+/g), JSON.stringify(other[key][i]).match(/\d+/g), `${key}[${i}] numeric promises`);
        });
      }
      assert.equal(lists.get('.screenshot-grid figure').length, t.screenshots.length);
      lists.get('.screenshot-grid figure').forEach((figure, i) => {
        assert.equal(figure.querySelector('figcaption').textContent, t.screenshots[i][0]);
        assert.equal(figure.querySelector('img').alt, t.screenshots[i][1]);
      });
      assert.equal(nodes.get('nav')['aria-label'], t.navLabel);
      assert.equal(nodes.get('.brand')['aria-label'], t.homeLabel);
      assert.equal(nodes.get('.hero-image')['aria-label'], t.heroLabel);
      assert.equal(nodes.get('.language-toggle')['aria-label'], t.toggle);
      if (current === 'fi') {
        assert(html.includes(t.featureIntro));
        t.screenshots.forEach(([caption, alt]) => {
          assert(html.includes(`<figcaption>${caption}</figcaption>`));
          assert(html.includes(`alt="${alt}"`));
        });
      }
      for (const [selector, key] of [['#features .feature-card', 'features'], ['#roadmap .feature-card', 'roadmapCards'], ['#release-notes .notes-list li', 'notes']]) {
        assert.equal(lists.get(selector).length, t[key].length, `${current} ${key}`);
        const heading = key === 'notes' ? 'strong' : 'h3';
        lists.get(selector).forEach((node, i) => assert.equal(node.querySelector(heading).textContent, t[key][i][0]));
      }
      assert.equal(t.controls.length, counts['.control-row span']);
      assert.equal(nodes.get('.release-callout p').textContent, t.releaseText);
      assert.equal(nodes.get('#release-notes .section-kicker').textContent, t.notesKicker);
      assert.doesNotMatch(JSON.stringify(t), /0\.18\.0/);
      assert.doesNotMatch(JSON.stringify(t), /tuleva päivitys|tulevassa päivityksessä|seuraava päivitys|next update|upcoming update|development branch|kehityshaarassa/i);
      assert.match(t.notesKicker, /UUSIN VERSIO|LATEST VERSION/);
      assert.doesNotMatch(JSON.stringify(t), technicalCopy);
      assert.match(nodes.get('.release-callout p').textContent, /Windows/);
      nodes.get('.language-toggle').listeners.click();
      assert.notEqual(document.documentElement.lang, current);
    }
  });
}

test('download links target the published installer and local images exist', () => {
  assert.doesNotMatch(html.replace(/<[^>]*>/g, ''), /0\.18\.0/);
  assert.doesNotMatch(html + script, /0\.17\.1alpha/);
  assert.doesNotMatch(html.replace(/<[^>]*>/g, ''), technicalCopy);
  const downloads = [...html.matchAll(/href="([^"]+releases\/download\/[^\"]+)"/g)];
  assert.equal(downloads.length, 3);
  for (const [, url] of downloads) assert.equal(url, 'https://github.com/emehtata/roadragetaxi/releases/download/v0.19.1alpha/RoadRageTrip-0.19.1alpha-Setup.exe');
  for (const [, asset] of html.matchAll(/(?:src|href)="(assets\/[^\"]+)"/g)) assert(fs.existsSync(path.join(__dirname, asset)), asset);
});
