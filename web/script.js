const translations = {
  fi: { navGame: 'Peli', navFeatures: 'Ominaisuudet', navHow: 'Näin pelaat', download: 'Lataa peli', release: 'Lataa uusin julkaisu', explore: 'Tutustu peliin', kicker: 'Avoimen maailman taksipeli · Suomi', title: 'Vie asiakkaat perille.<br><em>Haasta tie.</em>', copy: 'Oikeita suomalaisia katuja. Kohtuutonta liikennettä. Yksi taksinkuljettaja, jonka pinna on palanut.', introKicker: '01 / TYÖ', intro: 'Yksi kaupunki.<br><span>Loputtomasti tekosyitä.</span>', lead: 'The Road Rage Trip on ylhäältä kuvattu taksipeli, joka perustuu Suomen oikeisiin OpenStreetMap-katuihin.', introText: 'Nouda asiakkaat, pujottele vilkkailla kaduilla, väistä kaaosta ja vie heidät perille ennen kuin kärsivällisyytesi loppuu. Jokainen reitti on erilainen. Jokainen virhe maksaa.', featureKicker: '02 / KONEPELLIN ALLA', featureTitle: 'Kauniisti<br><em>ärtyneille.</em>', featureIntro: 'Tämä ei ole pelkkä tausta. Tieverkosto elää ja pistää vastaan.', features: [['Oikeita teitä, oikeita paikkoja', 'Aja suomalaisilla kaduilla, jotka muodostuvat OpenStreetMap-datasta rakennuksineen, puistoineen, vesistöineen ja kohteineen.'], ['Taksihommissa on särmää', 'Vastaanota kyytejä puhelimella, nouda asiakkaat, kerää bonuksia ja pidä mittari käynnissä arvaamattomassa liikenteessä.'], ['Pidä silmät tiessä', 'Piilossa olevat nopeuskamerat valvovat lähestymisalueita. Puut huojuvat, lehdet lentävät ja kova kolari saa taksin savuamaan.']], howKicker: '03 / RATTIIN', howTitle: 'Tunne<br><span>säännöt.</span><br>Riko rauha.', howLead: 'Kaupunki on sinun pelikenttäsi. Pisteet voit pilata itse.', controls: ['Aja, jarruta, ohjaa', 'Avaa taksin puhelin', 'Raivohuuto: raivaa tie', 'Avaa ohjeet ja tavoite', 'Tauko, asetukset, kaupungin vaihto'], releaseKicker: 'UUSIN JULKAISU', releaseTitle: 'Seuraava kyyti<br>odottaa.', releaseText: 'Lataa uusin Windows-versio GitHub Releases -sivulta ja lähde tien päälle.', releaseButton: 'Avaa GitHub Releases', scroll: 'VIERITÄ ALASPÄIN', toggle: 'Vaihda kieleksi English' },
  en: { navGame: 'Game', navFeatures: 'Features', navHow: 'How to play', download: 'Download', release: 'Download latest release', explore: 'Explore the game', kicker: 'Open-world taxi driving · Finland', title: 'Deliver fares.<br><em>Defy the road.</em>', copy: 'Real Finnish streets. Unreasonable traffic. One taxi driver who has had enough.', introKicker: '01 / THE JOB', intro: 'One city.<br><span>Infinite excuses.</span>', lead: 'The Road Rage Trip is a top-down taxi game powered by real OpenStreetMap roads from Finland.', introText: 'Pick up strangers, thread through living streets, dodge the chaos and get them there before your patience runs out. Every route is a little different. Every mistake costs.', featureKicker: '02 / UNDER THE HOOD', featureTitle: 'Built for the<br><em>beautifully irritated.</em>', featureIntro: 'Not a backdrop. A living road network that pushes back.', features: [['Real roads, real places', 'Drive Finnish city streets generated from live OSM geometry, with buildings, parks, water and named destinations.'], ['Taxi work with teeth', 'Find fares on your phone, pick up passengers, chase bonuses and keep the meter moving through unpredictable traffic.'], ['Eyes on the road', 'Hidden speed cameras watch their approach zones. Trees shake, leaves fly, and a hard enough crash leaves your taxi smoking.']], howKicker: '03 / TAKE THE WHEEL', howTitle: 'Know the<br><span>rules.</span><br>Break the calm.', howLead: 'The city is yours to navigate. The score is yours to ruin.', controls: ['Drive, brake, steer', 'Open the taxi phone', 'Rage shout: clear the way', 'Open controls and objective', 'Pause, settings, change city'], releaseKicker: 'LATEST RELEASE', releaseTitle: 'Your next fare<br>is waiting.', releaseText: 'Download the latest Windows build from GitHub Releases and hit the road.', releaseButton: 'Open GitHub Releases', scroll: 'SCROLL TO EXPLORE', toggle: 'Vaihda kieleksi Suomi' }
};
let language = 'fi';
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
