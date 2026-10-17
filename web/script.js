const translations = {
  fi: {
    navGame: 'Peli', navFeatures: 'Ominaisuudet', navRoadmap: 'Tulossa', navHow: 'Näin pelaat', navNotes: 'Julkaisutiedot', download: 'Lataa peli', release: 'Lataa Windows-asennus', explore: 'Tutustu peliin',
    kicker: 'Avoimen maailman taksipeli · Suomi', title: 'Asiakas kyytiin.<br><em>Raivo irti.</em>', copy: 'Oikeita suomalaisia katuja. Neljä vuodenaikaa. Taksamittari käy, ja asiakas arvioi jokaisen mutkan.',
    screenshotsKicker: 'PELIKUVIA / GODOT-ALPHA', platform: 'GODOT + PYTHON-PALVELIN', mapData: 'OIKEA OSM-DATA', openSource: 'AVOINTA LÄHDEKOODIA',
    screenshotsNote: 'Kuvat ovat aiemmista alpha-versioista; 0.18.0alpha on valmisteilla. Henkilöiden nimet arvotaan satunnaisesti, eivätkä ne tarkoita oikeita ihmisiä.',
    introKicker: '01 / TYÖ', intro: 'Yksi kaupunki.<br><span>Loputtomasti tekosyitä.</span>', lead: 'The Road Rage Trip on ylhäältä kuvattu taksipeli, joka perustuu Suomen oikeisiin OpenStreetMap-katuihin.',
    introText: 'Nouda asiakkaita puhelimesta, taksiasemilta tai kadulta. Aja heidät perille, seuraa ehdotettua reittiä ja pidä pisteesi kasassa, kun liikenne, kamerat, sää ja tie itse testaavat hermojasi.',
    featureKicker: '02 / KONEPELLIN ALLA', featureTitle: 'Kauniisti<br><em>ärtyneille.</em>', featureIntro: 'Tämä ei ole pelkkä tausta. Tieverkosto, sää, jalankulkijat ja sääntöjen rikkomisen seuraukset elävät ympärilläsi.',
    features: [
      ['Oikeita teitä, oikeita paikkoja', 'Aja suomalaisilla kaduilla, jotka muodostuvat OpenStreetMap-datasta rakennuksineen, puistoineen, vesistöineen, puineen ja nimettyine kohteineen.'],
      ['Raivo on polttoaineesi', 'Ylinopeus täyttää raivomittarin. Pura se huudolla: torvi pärähtää, kuljettaja kiroaa ja raivonaama mittarissa vääntyy irvistykseen.'],
      ['Kadut ovat täynnä muita kuskeja', 'Henkilöautot, pakettiautot, kuorma-autot ja bussit jakavat kadut kanssasi. Kolarista voi seurata tienvarren sanaharkka. Liikennekäyttäytymistä kehitetään edelleen: tämä on alpha, ei virheetön liikennesimulaattori.'],
      ['Pidä silmät tiellä', 'Piilossa olevat peltikamerat valvovat 50 metrin lähestymisalueita. Puut huojuvat, lehdet lentävät, ja kova kolari jättää taksin savuamaan ja pysähtyneeksi viideksi sekunniksi.'],
      ['Reitti elää', 'Paina N tai P ja avaa puhelin. Aktiivisella kyydillä se näyttää seuraavan käännöksen, etäisyyden ja kadunnimen. Vapaana sama puhelin näyttää kyytipyynnöt.'],
      ['Kaupunki kasvaa ympärillä', 'Uusia OSM-karttaruutuja haetaan taustalla ajon edetessä. Rakennukset, puistot, metsät, vesistöt ja jalankulkijat liittyvät maailmaan ilman latausruutua.'],
      ['Siltoja ja vesistöjä', 'Vesistöt renderöidään teiden alle, ja sillat kuljettavat liikenteen niiden yli omalla tasollaan. Tieverkko ja vesialueet muodostavat ajettavan kaupunkimaiseman.'],
      ['Sade kastelee tien', 'Sää muuttuu lennossa: sade kastelee tien vähitellen, lätäköt roiskuvat renkaiden alla ja märkä asfaltti vie pitoa juuri silloin kun sitä eniten tarvitset.'],
      ['Yö syttyy valoihin', 'OSM:n lyhtypylväitä täydentää tien mukaan luotu valaistus. Rakennusten ikkunat ja autojen ajovalot elävöittävät pimeitä katuja.'],
      ['Jalankulkijoilla on syke', 'Asukkaat kävelevät omille ovilleen, tarkistavat puhelintaan, istuvat penkillä tai lenkkeilevät - ja horjuvat baarista kotiin promillella 0.5-3.0. Yöllä he hohtavat himmeästi, ennen kuin ajovalo tai katulamppu löytää heidät.'],
      ['Liikennevalot ovat osa peliä', 'Risteykset ja liikennevalot ohjaavat sekä sinua että jalankulkijoita. Punaisia päin ajaminen näkyy suoraan taksin pistemäärässä.'],
      ['Neljä suomalaista vuodenaikaa', 'Valitse keikkakuskina aloituspäivä ja kellonaika. Lumi kertyy teille ja katoille, renkaat jättävät jälkiä ja auraajat puhdistavat katuja. Kevät tuo jäälautat, kesä vihreyden ja syksy ruskan.'],
      ['Jokainen kyyti kartuttaa kassaa', 'Taksamittari laskee lähtö-, kilometri- ja aikamaksun kellon mukaan. Seuraa hintaa ajon aikana, saa maksu perillä ja kasvata HUDissa näkyvää saldoa.'],
      ['Asiakas muistaa ajotyylisi', 'Törmäykset ja holtiton ajo syövät tyytyväisyyttä. Reipas, ajoissa perille päättyvä kyyti voi tuoda jopa kymmenen euron tipin.'],
      ['Junat kulkevat aikataulussa', 'Oikea VR:n aikataulu Digitrafficista: junat saapuvat valot päällä, asemalla kuulutetaan ja matkalaukkujen kanssa odottava asiakas on jo varannut kyytinsä.'],
      ['Sää Ilmatieteen laitokselta', 'Ota FMI-sää käyttöön: peli hakee havaintoja ja ennusteita pelin paikalle ja ajalle. Saatavuus vaihtelee; välimuisti ja tarvittaessa generoitu sää täydentävät puuttuvia tietoja.'],
      ['Tankki ei täyty itsestään', 'Polttoaine kuluu ajaessa. Aja huoltoasemalle, tankkaa pumpun hintaan ja palaa asiakkaiden pariin ennen kuin mittari näyttää tyhjää.'],
      ['Maan alle ja kerroksiin', 'Pysäköintihallit ja parkkitalot ovat mukana oikeasta OSM-datasta. Aja rampista alas, ja kaupunki vaihtuu betonikerrokseen - navigaattori osaa reitin sinnekin.'],
      ['RageCab soittaa', 'Sama siirrettävä puhelin näyttää vapaan taksin kyydit ja junamatkustajien ennakkotilaukset. Hyväksytyllä kyydillä se vaihtuu navigaattoriksi.'],
      ['Juhlat näkyvät kaupungissa', 'Uudenvuodenyön ilotulitukset, halloweenin kurpitsat ja lyhdyt sekä jouluaattona kaduilla kulkevat joulupukit seuraavat pelin kalenteria.'],
    ],
    roadmapKicker: '03 / SEURAAVAKSI', roadmapTitle: 'Tie jatkuu.<br><em>Kaaos kasvaa.</em>', roadmapIntro: 'Tämä rakennetaan saman asukas- ja jalankulkijamoottorin päälle, joka pyörittää peliä jo nyt.', roadmapSoon: 'TULOSSA',
    roadmapCards: [
      ['Idiootit pyörällä', 'Pyöräilijät liittyvät joukkoon: väistelevät, ajavat päin punaisia ja tekevät juuri sitä, mitä pyöräilijät parhaiten osaavat.'],
      ['Poliisin takaa-ajot', 'Piilokamerat eivät riitä ikuisesti. Oikeat poliisiautot lähtevät perään sireenit päällä, ja pakoon pääseminen vaatii muutakin kuin huudon.'],
      ['Taksikuskien tappelut', 'Kun raivo ei enää mahdu sanoihin, astu ulos autosta ja selvitä asia vanhalla tavalla.'],
    ],
    howKicker: '04 / RATTIIN', howTitle: 'Tunne<br><span>säännöt.</span><br>Riko rauha.', howLead: 'Kaupunki on sinun pelikenttäsi. Pisteet voit pilata itse.',
    controls: ['Aja, jarruta, ohjaa (myös nuolinäppäimet)', 'RageCab-puhelin: 1–3 hyväksyy, X hylkää', 'Raivohuuto: raivaa tie', 'Puhelin: kyytipyynnöt tai navigointi', 'Kaista-avustin', 'Nopeusrajoitin', 'Liikennevaloavustin', 'Respawn, T nollaa trippimittarin', 'Tauko, asetukset ja kaupungin vaihto', 'Astu taksiin tai ulos', 'Käynnistä tai sammuta moottori', 'Tankkaa huoltoasemalla', 'Junien saapumistaulu'],
    notesKicker: '05 / VALMISTEILLA 0.18.0alpha', notesTitle: 'Seuraava<br><em>päivitys.</em>', notesLead: '0.18.0alpha on kehityshaarassa, ei vielä ladattavana julkaisuna. Nyt ladattava Windows-versio on 0.17.1alpha.',
    notes: [
      ['Yksi kyyti, monta matkustajaa', 'Seuruekyydit kuljettavat enintään neljä matkustajaa. Alaikäiset matkustavat oman aikuisen vanhempansa kanssa pelin perhekäytännön mukaisesti.'],
      ['Sillat, rannat ja järvet', 'Korjauksia siltojen, rakennusten ja raiteiden tasoihin sekä rannikoihin ja järvien saariin. Järvialueiden kartanvalmistelua on rajattu turhan työn vähentämiseksi.'],
      ['Valoa ja varjoa', 'Auringon suunnan mukaan piirtyvät rakennusten varjot ja pidemmät, vastaantulevallekin kaistalle yltävät kaukovalot.'],
      ['Sää muistiin', 'FMI-historia säilyy välimuistissa. Epäonnistunut ennustepäivitys säilyttää aiemman ennusteen; puuttuva nykyhetki voi käyttää aiempaa tallennettua FMI-tuntia.'],
      ['Liikenteen ja aloituksen korjauksia', 'NPC-autojen turvavälit syntyessä, reitinhaun palautuminen ja kerrosten väliset törmäykset ovat saaneet korjauksia. Alpha-testit ja Windows-julkaisun tarkistukset jatkuvat.'],
    ],
    releaseKicker: 'LADATTAVISSA / 0.17.1alpha', releaseTitle: 'Seuraava kyyti<br>odottaa.', releaseText: 'Lataa Windows-asennuspaketti 0.17.1alpha. Peli on kehitysvaiheessa: virheitä ja suorituskykyongelmia voi esiintyä. 0.18.0alpha on valmisteilla.', releaseButton: 'Lataa Windows-asennus',
    scroll: 'VIERITÄ ALASPÄIN', toggle: 'Vaihda kieleksi English',
  },
  en: {
    navGame: 'Game', navFeatures: 'Features', navRoadmap: "What's next", navHow: 'How to play', navNotes: 'Release notes', download: 'Download', release: 'Download Windows installer', explore: 'Explore the game',
    kicker: 'Open-world taxi driving · Finland', title: 'Deliver fares.<br><em>Unleash the rage.</em>', copy: 'Real Finnish streets. Four changing seasons. The meter is running, and your passenger judges every turn.',
    screenshotsKicker: 'GAMEPLAY SCREENSHOTS / GODOT ALPHA', platform: 'GODOT + PYTHON SERVER', mapData: 'REAL OSM DATA', openSource: 'OPEN SOURCE',
    screenshotsNote: 'Screenshots show earlier alpha builds; 0.18.0alpha is in preparation. Character names are randomly generated and do not represent real people.',
    introKicker: '01 / THE JOB', intro: 'One city.<br><span>Infinite excuses.</span>', lead: 'The Road Rage Trip is a top-down taxi game powered by real OpenStreetMap roads from Finland.',
    introText: 'Pick up passengers from the phone, taxi stands, or the street. Get them there, follow the suggested route, and keep your score intact while traffic, cameras, weather, and the road itself test your patience.',
    featureKicker: '02 / UNDER THE HOOD', featureTitle: 'Built for the<br><em>beautifully irritated.</em>', featureIntro: 'Not a backdrop. Roads, weather, pedestrians, and consequences are alive around you.',
    features: [
      ['Real roads, real places', 'Drive Finnish city streets generated from OpenStreetMap data, with buildings, parks, forests, water, trees, and named destinations.'],
      ['Rage is your fuel gauge', 'Speeding fills your rage meter. Spend it with a shout: the horn blares, your driver curses, and the rage face on the meter twists into a grimace.'],
      ['The streets are full of other drivers', 'Cars, vans, trucks and buses share the streets with you. Crashes can lead to roadside arguments. Traffic behavior is still being refined: this is an alpha, not a flawless traffic simulator.'],
      ['Eyes on the road', 'Hidden speed cameras watch 50-meter approach zones on real roads. Trees sway, leaves fly, and a hard enough crash leaves the taxi smoking and stuck for five seconds.'],
      ['Routes that react', 'Press N or P to open the phone. During an active fare it shows the next turn, distance and street name. When you are free, the same phone shows ride requests.'],
      ['A city that keeps growing', 'New OSM map tiles stream in as you approach the edge of the loaded area. Buildings, scenery, water, and pedestrians join the world while you drive.'],
      ['Bridges and water', 'Water is rendered beneath the road network, while bridges carry traffic across it on their own layer. Roads and water areas shape the city you drive through.'],
      ['Rain that changes the drive', 'Weather shifts in real time: rain slowly wets the road, puddles splash under your tires, and wet asphalt steals your grip exactly when you need it most.'],
      ['The city lights up at night', 'Mapped OSM lamp posts are supplemented by lighting generated along roads. Glowing windows and vehicle headlights bring the dark streets to life.'],
      ['Pedestrians with a pulse', 'Residents walk to their own doors, check their phones, sit on benches, or go for a jog - and stumble home from the bar at 0.5-3.0 promille. At night they glow faintly until a headlight or streetlight finds them.'],
      ['Traffic lights play along', 'Junctions and signals guide both you and every pedestrian around you. Running a red shows up directly in the taxi score.'],
      ['Four Finnish seasons', 'Choose your starting date and time in freelance-driver mode. Snow accumulates on roads and roofs, tires leave tracks and ploughs clear the streets. Spring brings floating ice, summer greenery and autumn colors.'],
      ['Every fare grows your balance', 'The taxi meter combines a time-dependent starting fee with distance and time charges. Watch the price during the ride, collect at the destination, and build the balance shown in the HUD.'],
      ['Passengers remember your driving', 'Crashes and reckless driving hurt satisfaction. A fast ride that arrives on time can earn a tip of up to ten euros.'],
      ['Trains run on time', "The real train timetable from Digitraffic: trains roll in with headlights blazing, the station announces them, and a passenger with luggage has already booked your ride."],
      ['Weather from FMI', 'Opt in to observations and forecasts from the Finnish Meteorological Institute for your game location and time. Coverage varies; cached data and, when needed, generated weather fill the gaps.'],
      ['The tank won’t fill itself', "Fuel burns as you drive. Pull into a gas station, fill up at the pump price, and get back to your fares before the gauge hits empty."],
      ['Underground and upstairs', "Underground and multi-storey car parks come straight from OSM. Drive down the ramp and the city turns into a concrete deck - and the navigator knows the way in."],
      ['RageCab is calling', 'One movable phone handles ride requests and train-passenger prebookings while you are free. Accept a fare and it switches to navigation.'],
      ['Holidays come to town', 'New Year fireworks, Halloween pumpkins and lanterns, and Santas wandering the streets on Christmas Eve follow the game calendar.'],
    ],
    roadmapKicker: "03 / WHAT'S NEXT", roadmapTitle: 'The road continues.<br><em>Chaos grows.</em>', roadmapIntro: "This is just the start - all of it is being built on the same resident and pedestrian engine already running today.", roadmapSoon: 'SOON',
    roadmapCards: [
      ['Idiot cyclists', 'Cyclists join the chaos: weaving through traffic, running red lights, and doing exactly what cyclists do best.'],
      ['Police car chases', 'Hidden cameras only go so far. Real police cars will give chase with sirens on, and losing them will take more than a shout.'],
      ['Taxi driver brawls', "When rage doesn't fit in words anymore, step out of the car and settle it the old-fashioned way."],
    ],
    howKicker: '04 / TAKE THE WHEEL', howTitle: 'Know the<br><span>rules.</span><br>Break the calm.', howLead: 'The city is yours to navigate. The score is yours to ruin.',
    controls: ['Drive, brake, steer (arrow keys also work)', 'RageCab phone: 1–3 accept, X declines', 'Rage shout: clear the way', 'Phone: ride requests or navigation', 'Lane assist', 'Speed limiter', 'Traffic-light assist', 'Respawn, T resets trip meter', 'Pause, settings, change city', 'Enter or leave the taxi', 'Start or stop the engine', 'Refuel at a gas station', 'Train arrival board'],
    notesKicker: '05 / IN PREPARATION: 0.18.0alpha', notesTitle: 'The next<br><em>update.</em>', notesLead: '0.18.0alpha is on the development branch, not yet a downloadable release. The available Windows build is 0.17.1alpha.',
    notes: [
      ['One fare, several passengers', 'Group fares carry up to four passengers. Minors travel with their own adult parent under the game’s family policy.'],
      ['Bridges, coasts and lakes', 'Fixes to bridge, building and railway layers, coastlines and lake islands. Lake-region map preparation now avoids unnecessary work outside the fetched region.'],
      ['Light and shadow', 'Building shadows follow the sun, while longer high beams also cover the opposing lane.'],
      ['Weather worth remembering', 'FMI history stays cached. Failed forecast refreshes preserve the previous forecast; missing current-hour data can use an earlier cached FMI hour.'],
      ['Traffic and startup fixes', 'Safer NPC spawn clearances, route-recovery fixes and separation of collisions across map levels. Alpha testing and Windows release checks continue.'],
    ],
    releaseKicker: 'AVAILABLE / 0.17.1alpha', releaseTitle: 'Your next fare<br>is waiting.', releaseText: 'Download the 0.17.1alpha Windows installer. This is a work-in-progress alpha: bugs and performance issues remain. 0.18.0alpha is in preparation.', releaseButton: 'Download Windows installer',
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
  document.querySelectorAll('.hero-meta span').forEach((node, index) => {
    node.textContent = [t.platform, t.mapData, t.openSource][index];
  });
  document.querySelector('#screenshots-title').textContent = t.screenshotsKicker;
  document.querySelector('.screenshot-note').textContent = t.screenshotsNote;
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
