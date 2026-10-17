const translations = {
  fi: {
    navGame: 'Peli', navFeatures: 'Ominaisuudet', navRoadmap: 'Tulossa', navHow: 'Näin pelaat', navNotes: 'Julkaisutiedot', download: 'Lataa peli', release: 'Lataa Windows-asennus', explore: 'Tutustu peliin',
    kicker: 'Suomalainen taksi. Yliluonnollinen raivo.', title: 'Asiakas kyytiin.<br><em>Raivo irti.</em>', copy: 'Ruuhka ei väistä kohteliaisuudella. Kerää raivoa, huuda muut kuskit sivuun ja paina kaasu pohjaan. Uusimmassa versiossa taksin antisankarin raivo on todellinen supervoima.',
    screenshotsKicker: 'PELIKUVIA / GODOT-ALPHA', platform: 'GODOT + PYTHON-PALVELIN', mapData: 'OIKEA OSM-DATA', openSource: 'AVOINTA LÄHDEKOODIA',
    screenshotsNote: 'Kuvat ovat aiemmista alpha-versioista. Henkilöiden nimet arvotaan satunnaisesti, eivätkä ne tarkoita oikeita ihmisiä.',
    introKicker: '01 / ANTISANKARI', intro: 'Lyhyt pinna.<br><span>Yliluonnollinen raivo.</span>', lead: 'The Road Rage Trip on ylhäältä kuvattu taksipeli Suomen oikeilla kaduilla. Sinä olet sen antisankari: taksikuski, jonka raivo siirtää autot tieltä.',
    introText: 'Asiakas odottaa. Koko katu seisoo. Sinä et. Kun raivoa on tarpeeksi, paina SPACE ja huuda ruuhka helvettiin. Uusimmassa versiossa muut autot siirtyvät suoraan tien sivuun ja edessäsi pidetään ajoväylä auki vähintään kymmenen sekunnin ajan. Vaikka mittarissa olisi 210 km/h. Ei sankaripuheita. Taksamittari käy.',
    featureKicker: '02 / KONEPELLIN ALLA', featureTitle: 'Kauniisti<br><em>ärtyneille.</em>', featureIntro: 'Tämä ei ole pelkkä tausta. Tieverkosto, sää, jalankulkijat ja sääntöjen rikkomisen seuraukset elävät ympärilläsi.',
    features: [
      ['Oikeita teitä, oikeita paikkoja', 'Aja suomalaisilla kaduilla, jotka muodostuvat OpenStreetMap-datasta rakennuksineen, puistoineen, vesistöineen, puineen ja nimettyine kohteineen.'],
      ['Huuda ruuhka helvettiin', 'Raivo ei ole pelkkä ilme mittarissa. Se on supervoimasi. Ylinopeus kasvattaa raivoa; kun sitä riittää, SPACE raivaa muut autot sivuun. Raivohuuto pitää tien auki vähintään kymmeneksi sekunniksi ja raivaa sitä pidemmältä, mitä kovempaa ajat. Sinä painat kaasua. Muut väistävät.'],
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
      ['Junat kulkevat aikataulussa', 'Oikeat juna-aikataulut herättävät asemat eloon: junat saapuvat valot päällä, asemalla kuulutetaan ja matkalaukkujen kanssa odottava asiakas on jo varannut kyytinsä.'],
      ['Sää oikeasta maailmasta', 'Ota oikea sää käyttöön ja kohtaa valitsemasi paikan ja ajan keli ratin takana. Sade piiskaa tuulilasia, pakkanen puree ja liukas tie koettelee hermojasi. Asiakas haluaa silti perille.'],
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
    notesKicker: '05 / UUSIN VERSIO', notesTitle: 'Uusin<br><em>versio.</em>', notesLead: 'Uusimmassa versiossa raivo raivaa tien. Mukana myös seuruekyydit sekä parannuksia karttaan, säähän ja liikenteeseen.',
    notes: [
      ['Raivo on supervoima', 'Uusi raivohuuto siirtää NPC-autot suoraan tien sivuun ja pitää ajoväylän auki vähintään kymmenen sekuntia. Raivaus ulottuu kymmenen ajosekunnin päähän myös 210 km/h nopeudessa.'],
      ['Yksi kyyti, monta matkustajaa', 'Seuruekyydit kuljettavat enintään neljä matkustajaa. Alaikäiset matkustavat oman aikuisen vanhempansa kanssa pelin perhekäytännön mukaisesti.'],
      ['Sillat, rannat ja järvet', 'Korjauksia siltojen, rakennusten ja raiteiden tasoihin sekä rannikoihin ja järvien saariin. Järvialueiden kartanvalmistelua on rajattu turhan työn vähentämiseksi.'],
      ['Valoa ja varjoa', 'Auringon suunnan mukaan piirtyvät rakennusten varjot ja pidemmät, vastaantulevallekin kaistalle yltävät kaukovalot.'],
      ['Sää muistiin', 'Aiemmat säätiedot säilyvät tallessa. Jos ennusteen päivitys epäonnistuu tai nykyhetken tiedot puuttuvat, peli voi käyttää aiemmin tallennettua säätä.'],
      ['Liikenteen ja aloituksen korjauksia', 'NPC-autojen turvavälit syntyessä, reitinhaun palautuminen ja kerrosten väliset törmäykset ovat saaneet korjauksia. Alpha-testit ja Windows-julkaisun tarkistukset jatkuvat.'],
    ],
    releaseKicker: 'LADATTAVISSA / 0.17.1alpha', releaseTitle: 'Seuraava kyyti<br>odottaa.', releaseText: 'Lataa Windows-asennuspaketti 0.17.1alpha. Peli on kehitysvaiheessa: virheitä ja suorituskykyongelmia voi esiintyä.', releaseButton: 'Lataa Windows-asennus',
    scroll: 'VIERITÄ ALASPÄIN', toggle: 'Vaihda kieleksi English',
  },
  en: {
    navGame: 'Game', navFeatures: 'Features', navRoadmap: "What's next", navHow: 'How to play', navNotes: 'Release notes', download: 'Download', release: 'Download Windows installer', explore: 'Explore the game',
    kicker: 'Finnish taxi. Supernatural rage.', title: 'Deliver fares.<br><em>Unleash the rage.</em>', copy: 'Traffic won’t move for manners. Build rage, shout other drivers aside, and floor it. In the latest version, your taxi antihero’s rage is a real superpower.',
    screenshotsKicker: 'GAMEPLAY SCREENSHOTS / GODOT ALPHA', platform: 'GODOT + PYTHON SERVER', mapData: 'REAL OSM DATA', openSource: 'OPEN SOURCE',
    screenshotsNote: 'Screenshots show earlier alpha builds. Character names are randomly generated and do not represent real people.',
    introKicker: '01 / THE ANTIHERO', intro: 'Short fuse.<br><span>Supernatural rage.</span>', lead: 'The Road Rage Trip is a top-down taxi game on real Finnish streets. You are its antihero: a cab driver whose rage moves cars out of the way.',
    introText: 'Your passenger is waiting. The whole street is stuck. You aren’t. Build enough rage, hit SPACE, and shout traffic to hell. In the latest version, other cars move straight to the roadside and your path stays clear for at least ten seconds. Even at 210 km/h. No heroic speeches. The meter is running.',
    featureKicker: '02 / UNDER THE HOOD', featureTitle: 'Built for the<br><em>beautifully irritated.</em>', featureIntro: 'Not a backdrop. Roads, weather, pedestrians, and consequences are alive around you.',
    features: [
      ['Real roads, real places', 'Drive Finnish city streets generated from OpenStreetMap data, with buildings, parks, forests, water, trees, and named destinations.'],
      ['Shout traffic to hell', 'Rage isn’t just a face on your dashboard. It is your superpower. Speeding builds rage; with enough in the tank, SPACE shoves other cars aside. Your rage shout keeps the road clear for at least ten seconds, looking farther ahead the faster you drive. You floor it. They move.'],
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
      ['Trains run on time', "Real train timetables bring stations to life: trains roll in with headlights blazing, the station announces them, and a passenger with luggage has already booked your ride."],
      ['Weather from the real world', 'Switch on real weather and face the conditions for your chosen place and time. Rain lashes the windshield, frost bites, and slippery roads test your nerve. Your passenger still expects to get there.'],
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
    notesKicker: '05 / LATEST VERSION', notesTitle: 'The latest<br><em>version.</em>', notesLead: 'In the latest version, rage clears the road. Group fares and improvements to maps, weather and traffic round out the ride.',
    notes: [
      ['Rage is your superpower', 'The new rage shout moves NPC cars straight to the roadside and keeps your path clear for at least ten seconds. Clearance reaches ten driving seconds ahead, even at 210 km/h.'],
      ['One fare, several passengers', 'Group fares carry up to four passengers. Minors travel with their own adult parent under the game’s family policy.'],
      ['Bridges, coasts and lakes', 'Fixes to bridge, building and railway layers, coastlines and lake islands. Lake-region map preparation now avoids unnecessary work outside the fetched region.'],
      ['Light and shadow', 'Building shadows follow the sun, while longer high beams also cover the opposing lane.'],
      ['Weather worth remembering', 'Past weather data stays saved. If a forecast refresh fails or current conditions are unavailable, the game can use previously saved weather.'],
      ['Traffic and startup fixes', 'Safer NPC spawn clearances, route-recovery fixes and separation of collisions across map levels. Alpha testing and Windows release checks continue.'],
    ],
    releaseKicker: 'AVAILABLE / 0.17.1alpha', releaseTitle: 'Your next fare<br>is waiting.', releaseText: 'Download the 0.17.1alpha Windows installer. This is a work-in-progress alpha: bugs and performance issues remain.', releaseButton: 'Download Windows installer',
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
