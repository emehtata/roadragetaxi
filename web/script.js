const translations = {
  fi: {
    navGame: 'Peli', navFeatures: 'Ominaisuudet', navRoadmap: 'Tulossa', navHow: 'Näin pelaat', navNotes: 'Julkaisutiedot', download: 'Lataa peli', release: 'Lataa uusin julkaisu', explore: 'Tutustu peliin',
    kicker: 'Avoimen maailman taksipeli · Suomi', title: 'Vie asiakkaat perille.<br><em>Haasta tie.</em>', copy: 'Oikeita suomalaisia katuja. Elävää liikennettä. Yksi taksinkuljettaja, jonka raivo on supervoima.',
    introKicker: '01 / TYÖ', intro: 'Yksi kaupunki.<br><span>Loputtomasti tekosyitä.</span>', lead: 'The Road Rage Trip on ylhäältä kuvattu taksipeli, joka perustuu Suomen oikeisiin OpenStreetMap-katuihin.',
    introText: 'Nouda asiakkaita puhelimesta, taksiasemilta tai kadulta. Aja heidät perille, seuraa ehdotettua reittiä ja pidä pisteesi kasassa, kun liikenne, kamerat, sää ja tie itse testaavat hermojasi.',
    featureKicker: '02 / KONEPELLIN ALLA', featureTitle: 'Kauniisti<br><em>ärtyneille.</em>', featureIntro: 'Tämä ei ole pelkkä tausta. Tieverkosto, sää, jalankulkijat ja sääntöjen rikkomisen seuraukset elävät ympärilläsi.',
    features: [
      ['Oikeita teitä, oikeita paikkoja', 'Aja suomalaisilla kaduilla, jotka muodostuvat OpenStreetMap-datasta rakennuksineen, puistoineen, vesistöineen, puineen ja nimettyine kohteineen.'],
      ['Raivo on polttoaineesi', 'Ylinopeus täyttää raivomittarin. Pura se huudolla: torvi pärähtää, kuljettaja kiroaa ja raivonaama mittarissa vääntyy irvistykseen.'],
      ['Kadut ovat täynnä muita kuskeja', 'Autot, pakettiautot, kuorma-autot ja bussit ajavat, väistävät toisiaan ja parkkeeraavat oikeasti. Jos kaksi törmää, kuljettaja pysähtyy, astuu ulos, kiroilee tien varressa ja soittaa jollekulle - eikä palaa enää autoonsa.'],
      ['Pidä silmät tiellä', 'Piilossa olevat peltikamerat valvovat 50 metrin lähestymisalueita. Puut huojuvat, lehdet lentävät, ja kova kolari jättää taksin savuamaan ja pysähtyneeksi viideksi sekunniksi.'],
      ['Reitti elää', 'Paina N ja näet keltaisen ehdotetun reitin aktiiviselle kyydille. Reitti kunnioittaa yksisuuntaisia katuja ja laskee itsensä uudelleen, jos eksyt.'],
      ['Kaupunki kasvaa ympärillä', 'Uusia OSM-karttaruutuja haetaan taustalla ajon edetessä. Rakennukset, puistot, metsät, vesistöt ja jalankulkijat liittyvät maailmaan ilman latausruutua.'],
      ['Siltoja ja vesistöjä', 'Vesistöt renderöidään teiden alle, ja sillat kuljettavat liikenteen niiden yli omalla tasollaan. Tieverkko ja vesialueet muodostavat ajettavan kaupunkimaiseman.'],
      ['Sade kastelee tien', 'Sää muuttuu lennossa: sade kastelee tien vähitellen, lätäköt roiskuvat renkaiden alla ja märkä asfaltti vie pitoa juuri silloin kun sitä eniten tarvitset.'],
      ['Yö syttyy valoihin', 'Katuvalot ovat tarkalleen siellä, missä OpenStreetMap-data sanoo oikeiden lyhtypylväiden olevan, ja rakennusten ikkunat hehkuvat satunnaisesti pimeän tultua. Yöllä kaupunki näyttää siltä, missä joku oikeasti asuu.'],
      ['Jalankulkijoilla on syke', 'Asukkaat kävelevät omille ovilleen, tarkistavat puhelintaan, istuvat penkillä tai lenkkeilevät - ja horjuvat baarista kotiin promillella 0.5-3.0. Yöllä he hohtavat himmeästi, ennen kuin ajovalo tai katulamppu löytää heidät.'],
      ['Liikennevalot ovat osa peliä', 'Risteykset ja liikennevalot ohjaavat sekä sinua että jalankulkijoita. Punaisia päin ajaminen näkyy suoraan taksin pistemäärässä.'],
    ],
    roadmapKicker: '03 / SEURAAVAKSI', roadmapTitle: 'Tie jatkuu.<br><em>Kaaos kasvaa.</em>', roadmapIntro: 'Tämä rakennetaan saman asukas- ja jalankulkijamoottorin päälle, joka pyörittää peliä jo nyt.', roadmapSoon: 'TULOSSA',
    roadmapCards: [
      ['Idiootit pyörällä', 'Pyöräilijät liittyvät joukkoon: väistelevät, ajavat päin punaisia ja tekevät juuri sitä, mitä pyöräilijät parhaiten osaavat.'],
      ['Poliisin takaa-ajot', 'Piilokamerat eivät riitä ikuisesti. Oikeat poliisiautot lähtevät perään sireenit päällä, ja pakoon pääseminen vaatii muutakin kuin huudon.'],
      ['Taksikuskien tappelut', 'Kun raivo ei enää mahdu sanoihin, astu ulos autosta ja selvitä asia vanhalla tavalla.'],
    ],
    howKicker: '04 / RATTIIN', howTitle: 'Tunne<br><span>säännöt.</span><br>Riko rauha.', howLead: 'Kaupunki on sinun pelikenttäsi. Pisteet voit pilata itse.',
    controls: ['Aja, jarruta, ohjaa', 'Avaa taksin puhelin', 'Raivohuuto: raivaa tie', 'Näytä ehdotettu reitti', 'Kaista-avustin', 'Nopeusrajoitin', 'Liikennevaloavustin', 'Respawn, T nollaa trippimittarin', 'Tauko, asetukset ja kaupungin vaihto'],
    notesKicker: '05 / JULKAISU 0.12.0ALPHA', notesTitle: 'Mitä on<br><em>uutta.</em>', notesLead: 'Suurin päivitys tähän mennessä: kaupunki täyttyy eläväisestä, itsenäisestä liikenteestä.',
    notes: [
      ['Autonomiset ajoneuvot', 'Autot, pakettiautot, kuorma-autot ja bussit ajavat ja parkkeeraavat itsenäisesti kaduilla.'],
      ['Väistely käytössä', 'Liikenne väistää ja hidastaa esteen edessä sen sijaan että ajaisi läpi.'],
      ['Ei enää jumeja', 'Jumiin jäänyt ajoneuvo peruuttaa ja etsii uuden reitin sen sijaan että pyörisi paikallaan.'],
      ['Oikeita onnettomuuksia', 'Kun kaksi ajoneuvoa törmää, kuljettaja pysähtyy, astuu ulos, kiroilee ja soittaa jollekulle - eikä palaa enää autoon.'],
      ['Yö syttyy valoihin', 'Katuvalot seisovat oikeiden OpenStreetMap-lyhtypylväiden paikalla, ja rakennusten ikkunat hehkuvat satunnaisesti pimeällä.'],
      ['Asukkailla on arkea', 'Jalankulkijat tarkistavat puhelintaan, istuvat penkillä, lenkkeilevät ja jutustelevat toistensa kanssa.'],
      ['Tarkempi kartta', 'Liikenneympyrät, pysäytys- ja väistämismerkit sekä päällystetyt aukiot piirtyvät nyt kartalle.'],
    ],
    releaseKicker: 'UUSIN JULKAISU', releaseTitle: 'Seuraava kyyti<br>odottaa.', releaseText: 'Lataa uusin Windows-versio GitHub Releases -sivulta ja lähde tien päälle.', releaseButton: 'Avaa GitHub Releases',
    scroll: 'VIERITÄ ALASPÄIN', toggle: 'Vaihda kieleksi English',
  },
  en: {
    navGame: 'Game', navFeatures: 'Features', navRoadmap: "What's next", navHow: 'How to play', navNotes: 'Release notes', download: 'Download', release: 'Download latest release', explore: 'Explore the game',
    kicker: 'Open-world taxi driving · Finland', title: 'Deliver fares.<br><em>Unleash the rage.</em>', copy: 'Real Finnish streets. Living traffic. One taxi driver whose rage is a superpower.',
    introKicker: '01 / THE JOB', intro: 'One city.<br><span>Infinite excuses.</span>', lead: 'The Road Rage Trip is a top-down taxi game powered by real OpenStreetMap roads from Finland.',
    introText: 'Pick up passengers from the phone, taxi stands, or the street. Get them there, follow the suggested route, and keep your score intact while traffic, cameras, weather, and the road itself test your patience.',
    featureKicker: '02 / UNDER THE HOOD', featureTitle: 'Built for the<br><em>beautifully irritated.</em>', featureIntro: 'Not a backdrop. Roads, weather, pedestrians, and consequences are alive around you.',
    features: [
      ['Real roads, real places', 'Drive Finnish city streets generated from OpenStreetMap data, with buildings, parks, forests, water, trees, and named destinations.'],
      ['Rage is your fuel gauge', 'Speeding fills your rage meter. Spend it with a shout: the horn blares, your driver curses, and the rage face on the meter twists into a grimace.'],
      ['The streets are full of other drivers', 'Cars, vans, trucks, and buses drive, avoid each other, and actually park. If two collide, the driver stops, gets out, curses on the roadside, and calls someone - and never gets back in that car.'],
      ['Eyes on the road', 'Hidden speed cameras watch 50-meter approach zones on real roads. Trees sway, leaves fly, and a hard enough crash leaves the taxi smoking and stuck for five seconds.'],
      ['Routes that react', 'Press N to show a yellow suggested route to the active fare. It respects one-way streets and recalculates when you leave it.'],
      ['A city that keeps growing', 'New OSM map tiles stream in as you approach the edge of the loaded area. Buildings, scenery, water, and pedestrians join the world while you drive.'],
      ['Bridges and water', 'Water is rendered beneath the road network, while bridges carry traffic across it on their own layer. Roads and water areas shape the city you drive through.'],
      ['Rain that changes the drive', 'Weather shifts in real time: rain slowly wets the road, puddles splash under your tires, and wet asphalt steals your grip exactly when you need it most.'],
      ['The city lights up at night', "Streetlights stand exactly where OpenStreetMap says real lamp posts stand, and building windows glow at random once it's dark. At night, the city looks like somewhere people actually live."],
      ['Pedestrians with a pulse', 'Residents walk to their own doors, check their phones, sit on benches, or go for a jog - and stumble home from the bar at 0.5-3.0 promille. At night they glow faintly until a headlight or streetlight finds them.'],
      ['Traffic lights play along', 'Junctions and signals guide both you and every pedestrian around you. Running a red shows up directly in the taxi score.'],
    ],
    roadmapKicker: "03 / WHAT'S NEXT", roadmapTitle: 'The road continues.<br><em>Chaos grows.</em>', roadmapIntro: "This is just the start - all of it is being built on the same resident and pedestrian engine already running today.", roadmapSoon: 'SOON',
    roadmapCards: [
      ['Idiot cyclists', 'Cyclists join the chaos: weaving through traffic, running red lights, and doing exactly what cyclists do best.'],
      ['Police car chases', 'Hidden cameras only go so far. Real police cars will give chase with sirens on, and losing them will take more than a shout.'],
      ['Taxi driver brawls', "When rage doesn't fit in words anymore, step out of the car and settle it the old-fashioned way."],
    ],
    howKicker: '04 / TAKE THE WHEEL', howTitle: 'Know the<br><span>rules.</span><br>Break the calm.', howLead: 'The city is yours to navigate. The score is yours to ruin.',
    controls: ['Drive, brake, steer', 'Open the taxi phone', 'Rage shout: clear the way', 'Show suggested route', 'Lane assist', 'Speed limiter', 'Traffic-light assist', 'Respawn, T resets trip meter', 'Pause, settings, change city'],
    notesKicker: '05 / RELEASE 0.12.0ALPHA', notesTitle: "What's<br><em>new.</em>", notesLead: "The biggest update yet: the city fills up with living, independent traffic.",
    notes: [
      ['Autonomous vehicles', 'Cars, vans, trucks, and buses drive and park on their own around the streets.'],
      ['Avoidance is live', 'Traffic slows and steers around obstacles instead of driving straight through them.'],
      ['No more getting stuck', 'A blocked vehicle reverses and finds a new route instead of spinning in place forever.'],
      ['Real accidents', "When two vehicles collide, the driver stops, gets out, curses, and calls someone - and never gets back in the car."],
      ['The city lights up at night', 'Streetlights stand where real OpenStreetMap lamp posts stand, and building windows glow at random in the dark.'],
      ['Residents have a life', 'Pedestrians check their phones, sit on benches, go jogging, and chat with each other.'],
      ['A more accurate map', 'Roundabouts, stop/yield signs, and paved plazas now render on the map.'],
    ],
    releaseKicker: 'LATEST RELEASE', releaseTitle: 'Your next fare<br>is waiting.', releaseText: 'Download the latest Windows build from GitHub Releases and hit the road.', releaseButton: 'Open GitHub Releases',
    scroll: 'SCROLL TO EXPLORE', toggle: 'Vaihda kieleksi Suomi',
  },
};

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
  navLinks[2].textContent = t.navRoadmap;
  navLinks[3].textContent = t.navHow;
  navLinks[4].textContent = t.navNotes;
  navLinks[5].innerHTML = `${t.download} <span aria-hidden="true">↗</span>`;
  document.querySelector('.hero-copy').textContent = t.copy;
  document.querySelector('.hero h1').innerHTML = t.title;
  document.querySelector('.hero-actions .button-primary').innerHTML = `${t.release} <span>↗</span>`;
  document.querySelector('.hero-actions .button-ghost').innerHTML = `${t.explore} <span>↓</span>`;
  document.querySelector('.intro h2').innerHTML = t.intro;
  document.querySelector('.intro .lead').textContent = t.lead;
  document.querySelector('.intro-grid > div p:last-child').textContent = t.introText;
  document.querySelector('.intro .section-kicker').textContent = t.introKicker;
  document.querySelector('.hero .eyebrow').lastChild.textContent = ` ${t.kicker}`;
  document.querySelector('#features .section-kicker').textContent = t.featureKicker;
  document.querySelector('#features .feature-heading h2').innerHTML = t.featureTitle;
  document.querySelector('#features .feature-heading p').textContent = t.featureIntro;
  document.querySelectorAll('#features .feature-card').forEach((card, index) => {
    card.querySelector('h3').textContent = t.features[index][0];
    card.querySelector('p').textContent = t.features[index][1];
  });
  document.querySelector('#roadmap .section-kicker').textContent = t.roadmapKicker;
  document.querySelector('#roadmap .feature-heading h2').innerHTML = t.roadmapTitle;
  document.querySelector('#roadmap .feature-heading p').textContent = t.roadmapIntro;
  document.querySelectorAll('#roadmap .feature-card').forEach((card, index) => {
    card.querySelector('.feature-number').textContent = t.roadmapSoon;
    card.querySelector('h3').textContent = t.roadmapCards[index][0];
    card.querySelector('p').textContent = t.roadmapCards[index][1];
  });
  document.querySelector('.how .section-kicker').textContent = t.howKicker;
  document.querySelector('.how h2').innerHTML = t.howTitle;
  document.querySelector('.how .lead').textContent = t.howLead;
  document.querySelector('#release-notes .section-kicker').textContent = t.notesKicker;
  document.querySelector('#release-notes h2').innerHTML = t.notesTitle;
  document.querySelector('#release-notes .lead').textContent = t.notesLead;
  document.querySelectorAll('#release-notes .notes-list li').forEach((item, index) => {
    item.querySelector('strong').textContent = t.notes[index][0];
    item.lastChild.textContent = t.notes[index][1];
  });
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
