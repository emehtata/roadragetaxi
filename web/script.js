const translations = {
  fi: { navGame: 'Peli', navFeatures: 'Ominaisuudet', navHow: 'Näin pelaat', download: 'Lataa peli', release: 'Lataa uusin julkaisu', explore: 'Tutustu peliin', kicker: 'Avoimen maailman taksipeli · Suomi', title: 'Vie asiakkaat perille.<br><em>Haasta tie.</em>', copy: 'Oikeita suomalaisia katuja. Elävää liikennettä. Yksi taksinkuljettaja, jonka raivo on supervoima.', introKicker: '01 / TYÖ', intro: 'Yksi kaupunki.<br><span>Loputtomasti tekosyitä.</span>', lead: 'The Road Rage Trip on ylhäältä kuvattu taksipeli, joka perustuu Suomen oikeisiin OpenStreetMap-katuihin.', introText: 'Nouda asiakkaita puhelimesta, taksiasemilta tai kadulta. Aja heidät perille, seuraa ehdotettua reittiä ja pidä pisteesi kasassa, kun liikenne, kamerat ja tie itse testaavat hermojasi.', featureKicker: '02 / KONEPELLIN ALLA', featureTitle: 'Kauniisti<br><em>ärtyneille.</em>', featureIntro: 'Tämä ei ole pelkkä tausta. Tieverkosto, liikenne ja sääntöjen rikkomisen seuraukset elävät ympärilläsi.', features: [['Oikeita teitä, oikeita paikkoja', 'Aja suomalaisilla kaduilla, jotka muodostuvat OpenStreetMap-datasta rakennuksineen, puistoineen, vesistöineen, puineen ja nimettyine kohteineen.'], ['Raivo on supervoimasi', 'Käytä raivoa raivataksesi tien liikenteen läpi. Poliisi voi lähteä perääsi, mutta yksi hyvin ajoitettu huuto saa poliisiauton kääntymään pois.'], ['Pidä silmät tiessä', 'Tien oikealle reunalle sijoitetut peltikamerat valvovat 50 metrin lähestymisalueita. Liikennevalot, kolarit ja puiden kaatumiset muuttavat ajon seurauksia.'], ['Reitti elää', 'Paina N ja näet keltaisen ehdotetun reitin aktiiviselle kyydille. Reitti kunnioittaa yksisuuntaisia katuja ja laskee itsensä uudelleen, jos eksyt.'], ['Kaupunki kasvaa ympärillä', 'Uusia OSM-karttaruutuja haetaan taustalla ajon edetessä. Rakennukset, puistot, metsät, vesistöt ja liikenne liittyvät maailmaan ilman latausruutua.'], ['Siltoja ja vesistöjä', 'Vesistöt renderöidään teiden alle, ja sillat kuljettavat liikenteen niiden yli omalla tasollaan. Kartan korkeuserot näkyvät myös ajossa.']], howKicker: '03 / RATTIIN', howTitle: 'Tunne<br><span>säännöt.</span><br>Riko rauha.', howLead: 'Kaupunki on sinun pelikenttäsi. Pisteet voit pilata itse.', controls: ['Aja, jarruta, ohjaa', 'Avaa taksin puhelin', 'Raivohuuto: raivaa tie', 'Näytä ehdotettu reitti', 'Kaista-avustin', 'Nopeusrajoitin', 'Liikennevaloavustin', 'Respawn, T nollaa trippimittarin', 'Tauko, asetukset ja kaupungin vaihto'], releaseKicker: 'UUSIN JULKAISU', releaseTitle: 'Seuraava kyyti<br>odottaa.', releaseText: 'Lataa uusin Windows-versio GitHub Releases -sivulta ja lähde tien päälle.', releaseButton: 'Avaa GitHub Releases', scroll: 'VIERITÄ ALASPÄIN', toggle: 'Vaihda kieleksi English' },
  en: { navGame: 'Game', navFeatures: 'Features', navHow: 'How to play', download: 'Download', release: 'Download latest release', explore: 'Explore the game', kicker: 'Open-world taxi driving · Finland', title: 'Deliver fares.<br><em>Unleash the rage.</em>', copy: 'Real Finnish streets. Living traffic. One taxi driver whose rage is a superpower.', introKicker: '01 / THE JOB', intro: 'One city.<br><span>Infinite excuses.</span>', lead: 'The Road Rage Trip is a top-down taxi game powered by real OpenStreetMap roads from Finland.', introText: 'Pick up passengers from the phone, taxi stands, or the street. Get them there, follow the suggested route, and keep your score intact while traffic, cameras, and the road test your patience.', featureKicker: '02 / UNDER THE HOOD', featureTitle: 'Built for the<br><em>beautifully irritated.</em>', featureIntro: 'Not a backdrop. Roads, traffic, and consequences are alive around you.', features: [['Real roads, real places', 'Drive Finnish city streets generated from OpenStreetMap data, with buildings, parks, forests, water, trees, and named destinations.'], ['Road rage is your superpower', 'Spend your rage to clear a path through traffic. Police may pursue you, but one well-timed shout can make a police car turn away.'], ['Eyes on the road', 'Speed cameras sit on the right side of the road and watch 50-meter approach zones. Traffic lights, crashes, and falling trees make every drive count.'], ['Routes that react', 'Press N to show a yellow suggested route to the active fare. It respects one-way streets and recalculates when you leave it.'], ['A city that keeps growing', 'New OSM map tiles stream in as you approach the edge of the loaded area. Buildings, scenery, water, and traffic join the world while you drive.'], ['Bridges and water', 'Water is rendered beneath the road network, while bridges carry traffic across it on their own layer. Map elevation matters when you drive.']], howKicker: '03 / TAKE THE WHEEL', howTitle: 'Know the<br><span>rules.</span><br>Break the calm.', howLead: 'The city is yours to navigate. The score is yours to ruin.', controls: ['Drive, brake, steer', 'Open the taxi phone', 'Rage shout: clear the way', 'Show suggested route', 'Lane assist', 'Speed limiter', 'Traffic-light assist', 'Respawn, T resets trip meter', 'Pause, settings, change city'], releaseKicker: 'LATEST RELEASE', releaseTitle: 'Your next fare<br>is waiting.', releaseText: 'Download the latest Windows build from GitHub Releases and hit the road.', releaseButton: 'Open GitHub Releases', scroll: 'SCROLL TO EXPLORE', toggle: 'Vaihda kieleksi Suomi' }
};
translations.fi.features[5][1] = 'Vesistöt renderöidään teiden alle, ja sillat kuljettavat liikenteen niiden yli omalla tasollaan. Tieverkko ja vesialueet muodostavat ajettavan kaupunkimaiseman.';
translations.en.features[5][1] = 'Water is rendered beneath the road network, while bridges carry traffic across it on their own layer. Roads and water areas shape the city you drive through.';
const browserLanguage = (navigator.languages && navigator.languages[0]) || navigator.language || 'fi';
let language = browserLanguage.toLowerCase().startsWith('fi') ? 'fi' : 'en';
const toggle = document.querySelector('.language-toggle');
const navLinks = document.querySelectorAll('nav a');
const controls = document.querySelectorAll('.control-row span');
function setLanguage(next) {
  language = next;
  const t = translations[language];
  navLinks[0].textContent = t.navGame;
  navLinks[1].textContent = t.navFeatures;
  navLinks[2].textContent = t.navHow;
  navLinks[3].innerHTML = `${t.download} <span aria-hidden="true">↗</span>`;
  document.querySelector('.hero-copy').textContent = t.copy;
  document.querySelector('.hero h1').innerHTML = t.title;
  document.querySelector('.hero-actions .button-primary').innerHTML = `${t.release} <span>↗</span>`;
  document.querySelector('.hero-actions .button-ghost').innerHTML = `${t.explore} <span>↓</span>`;
  document.querySelector('.intro h2').innerHTML = t.intro;
  document.querySelector('.intro .lead').textContent = t.lead;
  document.querySelector('.intro-grid > div p:last-child').textContent = t.introText;
  document.querySelector('.intro .section-kicker').textContent = t.introKicker;
  document.querySelector('.hero .eyebrow').lastChild.textContent = ` ${t.kicker}`;
  document.querySelector('.feature-band .section-kicker').textContent = t.featureKicker;
  document.querySelector('.feature-heading h2').innerHTML = t.featureTitle;
  document.querySelector('.feature-heading p').textContent = t.featureIntro;
  document.querySelectorAll('.feature-card').forEach((card, index) => {
    card.querySelector('h3').textContent = t.features[index][0];
    card.querySelector('p').textContent = t.features[index][1];
  });
  document.querySelector('.how .section-kicker').textContent = t.howKicker;
  document.querySelector('.how h2').innerHTML = t.howTitle;
  document.querySelector('.how .lead').textContent = t.howLead;
  document.querySelector('.release-marker').textContent = t.releaseKicker;
  document.querySelector('.release-callout h2').innerHTML = t.releaseTitle;
  document.querySelector('.release-callout p').textContent = t.releaseText;
  document.querySelector('.release-callout .button').innerHTML = `${t.releaseButton} <span>↗</span>`;
  document.querySelector('.hero-scroll').firstChild.textContent = ` ${t.scroll} `;
  controls.forEach((node, index) => { node.textContent = t.controls[index]; });
  toggle.textContent = language === 'fi' ? 'EN' : 'FI';
  toggle.setAttribute('aria-label', t.toggle);
  document.documentElement.lang = language;
}
toggle.addEventListener('click', () => setLanguage(language === 'fi' ? 'en' : 'fi'));
setLanguage(language);
