const translations = {
  fi: {
    navGame: 'Peli', navFeatures: 'Ominaisuudet', navRoadmap: 'Tulossa', navHow: 'Näin pelaat', navNotes: 'Julkaisutiedot', download: 'Lataa peli', release: 'Lataa Windows-asennus', explore: 'Tutustu peliin',
    kicker: 'Suomalainen taksi. Yliluonnollinen raivo.', title: 'Asiakas kyytiin.<br><em>Raivo irti.</em>', copy: 'Ruuhka ei väistä kohteliaisuudella. Kerää raivoa, huuda muut kuskit sivuun ja paina kaasu pohjaan. Uusimmassa versiossa taksin antisankarin raivo on todellinen supervoima.',
    screenshotsKicker: 'PELIKUVIA', platform: 'SUOMALAINEN TAKSISEIKKAILU', mapData: 'OIKEAT SUOMALAISET KADUT', openSource: 'SINÄ RATISSA',
    screenshotsNote: 'Kuvat ovat aiemmista peliversioista. Henkilöiden nimet arvotaan satunnaisesti, eivätkä ne tarkoita oikeita ihmisiä.',
    screenshots: [
      ['Kaupunki ja junat', 'Helsinki päivällä: vesistöt, sillat ja junien saapumistaulu'],
      ['Yöruuhka', 'Iltaruuhka Helsingin valaistuilla kaduilla'],
      ['Talvi ja junat', 'Lumisade Oulun asemalla, juna raiteilla'],
      ['RageCab-puhelin', 'RageCab-puhelin sateisessa Helsingissä: junamatkustajan ennakkotilaus ja kyytipyyntö rinnakkain'],
      ['Suomen kartta', 'Aloituspaikan valinta Suomen kartalta'],
      ['Sääennuste', 'Aloitusnäyttö ja oikea sääennuste'],
    ],
    navLabel: 'Päänavigaatio', homeLabel: 'The Road Rage Tripin etusivu', heroLabel: 'The Road Rage Tripin latauskuva',
    introKicker: '01 / ANTISANKARI', intro: 'Lyhyt pinna.<br><span>Yliluonnollinen raivo.</span>', lead: 'The Road Rage Trip on ylhäältä kuvattu taksipeli Suomen oikeilla kaduilla. Sinä olet sen antisankari: taksikuski, jonka raivo siirtää autot tieltä.',
    introText: 'Asiakas odottaa. Koko katu seisoo. Sinä et. Kun raivoa on tarpeeksi, paina SPACE ja huuda ruuhka helvettiin. Uusimmassa versiossa muut autot siirtyvät suoraan tien sivuun ja edessäsi pidetään ajoväylä auki vähintään kymmenen sekunnin ajan. Vaikka mittarissa olisi 210 km/h. Ei sankaripuheita. Taksamittari käy.',
    featureKicker: '02 / KONEPELLIN ALLA', featureTitle: 'Kauniisti<br><em>ärtyneille.</em>', featureIntro: 'Tämä ei ole pelkkä tausta. Tieverkosto, sää, jalankulkijat ja sääntöjen rikkomisen seuraukset elävät ympärilläsi.',
    features: [
      ['Oikeita teitä, oikeita paikkoja', 'Tunnista tuttu risteys, oikaise puiston ohi ja etsi asiakkaan osoite. Oikeat suomalaiset kadut ovat sinun pelikenttäsi.'],
      ['Huuda ruuhka helvettiin', 'Raivo ei ole pelkkä ilme mittarissa. Se on supervoimasi. Ylinopeus kasvattaa raivoa; kun sitä riittää, SPACE raivaa muut autot sivuun. Raivohuuto pitää tien auki vähintään kymmeneksi sekunniksi ja raivaa sitä pidemmältä, mitä kovempaa ajat. Sinä painat kaasua. Muut väistävät.'],
      ['Kadut ovat täynnä muita kuskeja', 'Henkilöautot, pakettiautot, kuorma-autot ja bussit jakavat kadut kanssasi. Kolarista voi seurata tienvarren sanaharkka. Pidä pää kylmänä – tai kerää tarpeeksi raivoa ja huuda tie auki.'],
      ['Pidä silmät tiellä', 'Peltikamera voi yllättää juuri kun vauhti alkaa maistua. Puut huojuvat, lehdet lentävät, ja kova kolari jättää taksin savuamaan ja pysähtyneeksi viideksi sekunniksi.'],
      ['Reitti elää', 'Paina N tai P ja avaa puhelin. Aktiivisella kyydillä se näyttää seuraavan käännöksen, etäisyyden ja kadunnimen. Vapaana sama puhelin näyttää kyytipyynnöt.'],
      ['Kaupunki kasvaa ympärillä', 'Jatka tutuilta kaduilta kohti uusia maisemia. Keskusta vaihtuu lähiöihin, metsiin ja rantateihin, ja seuraava asiakas odottaa jo jossain edessä.'],
      ['Siltoja ja vesistöjä', 'Ylitä joki, seuraa rantatietä ja löydä reitti siltojen kautta. Vesi tekee maisemasta kauniin, mutta taksisi paikka on kuivalla maalla.'],
      ['Sade kastelee tien', 'Sää muuttuu lennossa: sade kastelee tien vähitellen, lätäköt roiskuvat renkaiden alla ja märkä asfaltti vie pitoa juuri silloin kun sitä eniten tarvitset.'],
      ['Yö syttyy valoihin', 'Katuvalot, hehkuvat ikkunat ja vastaantulijoiden ajovalot halkovat pimeyttä. Yövuorossa tuttu kaupunki näyttää toiset kasvonsa.'],
      ['Jalankulkijoilla on syke', 'Asukkaat kävelevät omille ovilleen, tarkistavat puhelintaan, istuvat penkillä tai lenkkeilevät – ja horjuvat baarista kotiin. Pidä silmät auki: kaikki eivät kulje suoraan.'],
      ['Liikennevalot ovat osa peliä', 'Risteykset ja liikennevalot ohjaavat sekä sinua että jalankulkijoita. Punaisia päin ajaminen näkyy suoraan taksin pistemäärässä.'],
      ['Neljä suomalaista vuodenaikaa', 'Valitse keikkakuskina aloituspäivä ja kellonaika. Lumi kertyy teille ja katoille, renkaat jättävät jälkiä ja auraajat puhdistavat katuja. Kevät tuo jäälautat, kesä vihreyden ja syksy ruskan.'],
      ['Jokainen kyyti kartuttaa kassaa', 'Mittari käy, matka etenee ja kassa kasvaa. Vie asiakas perille, nappaa maksu ja etsi seuraava kyyti.'],
      ['Asiakas muistaa ajotyylisi', 'Törmäykset ja holtiton ajo syövät tyytyväisyyttä. Reipas, ajoissa perille päättyvä kyyti voi tuoda jopa kymmenen euron tipin.'],
      ['Junat kulkevat aikataulussa', 'Oikeat juna-aikataulut herättävät asemat eloon: junat saapuvat valot päällä, asemalla kuulutetaan ja matkalaukkujen kanssa odottava asiakas on jo varannut kyytinsä.'],
      ['Sää oikeasta maailmasta', 'Ota oikea sää käyttöön ja kohtaa valitsemasi paikan ja ajan keli ratin takana. Sade piiskaa tuulilasia, pakkanen puree ja liukas tie koettelee hermojasi. Asiakas haluaa silti perille.'],
      ['Tankki ei täyty itsestään', 'Polttoaine kuluu ajaessa. Aja huoltoasemalle, tankkaa pumpun hintaan ja palaa asiakkaiden pariin ennen kuin mittari näyttää tyhjää.'],
      ['Maan alle ja kerroksiin', 'Kaikki asiakkaat eivät odota kadunkulmassa. Aja rampista pysäköintihalliin ja nouda kyyti myös maan alta – navigaattori näyttää tietä.'],
      ['RageCab soittaa', 'Sama siirrettävä puhelin näyttää vapaan taksin kyydit ja junamatkustajien ennakkotilaukset. Hyväksytyllä kyydillä se vaihtuu navigaattoriksi.'],
      ['Juhlat näkyvät kaupungissa', 'Uudenvuodenyön ilotulitukset, halloweenin kurpitsat ja lyhdyt sekä jouluaattona kaduilla kulkevat joulupukit seuraavat pelin kalenteria.'],
    ],
    roadmapKicker: '03 / SEURAAVAKSI', roadmapTitle: 'Tie jatkuu.<br><em>Kaaos kasvaa.</em>', roadmapIntro: 'Kaupunki ei aio tehdä työvuorostasi helpompaa. Seuraavaksi kaduille on luvassa vielä lisää hankaluuksia.', roadmapSoon: 'TULOSSA',
    roadmapCards: [
      ['Idiootit pyörällä', 'Pyöräilijät liittyvät joukkoon: väistelevät, ajavat päin punaisia ja tekevät juuri sitä, mitä pyöräilijät parhaiten osaavat.'],
      ['Poliisin takaa-ajot', 'Piilokamerat eivät riitä ikuisesti. Oikeat poliisiautot lähtevät perään sireenit päällä, ja pakoon pääseminen vaatii muutakin kuin huudon.'],
      ['Taksikuskien tappelut', 'Kun raivo ei enää mahdu sanoihin, astu ulos autosta ja selvitä asia vanhalla tavalla.'],
    ],
    howKicker: '04 / RATTIIN', howTitle: 'Tunne<br><span>säännöt.</span><br>Riko rauha.', howLead: 'Kaupunki on sinun pelikenttäsi. Pisteet voit pilata itse.',
    controls: ['Aja, jarruta, ohjaa (myös nuolinäppäimet)', 'RageCab-puhelin: 1–3 hyväksyy, X hylkää', 'Raivohuuto: raivaa tie', 'Puhelin: kyytipyynnöt tai navigointi', 'Kaista-avustin', 'Nopeusrajoitin', 'Liikennevaloavustin', 'Palauta taksi tielle, T nollaa trippimittarin', 'Tauko, asetukset ja kaupungin vaihto', 'Astu taksiin tai ulos', 'Käynnistä tai sammuta moottori', 'Tankkaa huoltoasemalla', 'Junien saapumistaulu'],
    notesKicker: '05 / UUSIN VERSIO', notesTitle: 'Uusin<br><em>versio.</em>', notesLead: 'Uusimmassa versiossa raivo raivaa tien. Mukana myös seuruekyydit sekä parannuksia karttaan, säähän ja liikenteeseen.',
    notes: [
      ['Raivo on supervoima', 'Uusi raivohuuto siirtää muut autot suoraan tien sivuun ja pitää ajoväylän auki vähintään kymmenen sekuntia. Raivaus ulottuu kymmenen ajosekunnin päähän myös 210 km/h nopeudessa.'],
      ['Yksi kyyti, monta matkustajaa', 'Seuruekyydit kuljettavat enintään neljä matkustajaa. Lapset matkustavat vanhempansa seurassa.'],
      ['Sillat, rannat ja järvet', 'Selkeämmät sillat, rannat ja saaret tekevät reitin löytämisestä helpompaa. Myös järviseudulla pääset nopeammin ratin taakse.'],
      ['Valoa ja varjoa', 'Auringon suunnan mukaan piirtyvät rakennusten varjot ja pidemmät, vastaantulevallekin kaistalle yltävät kaukovalot.'],
      ['Keli jatkuu, vuoro vaihtuu', 'Palaa samaan paikkaan ja aikaan ilman yllättävää kelinvaihdosta. Sää pysyy aiempaa johdonmukaisempana pelikertojen välillä.'],
      ['Sujuvammin matkaan', 'Muut autot ilmestyvät turvallisemman välimatkan päähän, ja eksyneet kuskit löytävät paremmin takaisin reitille. Vähemmän turhia esteitä, enemmän ajamista.'],
    ],
    releaseKicker: 'LADATTAVISSA / 0.17.1alpha', releaseTitle: 'Seuraava kyyti<br>odottaa.', releaseText: 'Lataa Windows-asennuspaketti 0.17.1alpha. Peli on kehitysvaiheessa: virheitä ja suorituskykyongelmia voi esiintyä.', releaseButton: 'Lataa Windows-asennus',
    scroll: 'VIERITÄ ALASPÄIN', toggle: 'Vaihda englanniksi',
  },
  en: {
    navGame: 'Game', navFeatures: 'Features', navRoadmap: "What's next", navHow: 'How to play', navNotes: 'Release notes', download: 'Download', release: 'Download Windows installer', explore: 'Explore the game',
    kicker: 'Finnish taxi. Supernatural rage.', title: 'Deliver fares.<br><em>Unleash the rage.</em>', copy: 'Traffic won’t move for manners. Build rage, shout other drivers aside, and floor it. In the latest version, your taxi antihero’s rage is a real superpower.',
    screenshotsKicker: 'GAMEPLAY SCREENSHOTS', platform: 'FINNISH TAXI ADVENTURE', mapData: 'REAL FINNISH STREETS', openSource: 'YOU AT THE WHEEL',
    screenshotsNote: 'Screenshots show earlier game versions. Character names are randomly generated and do not represent real people.',
    screenshots: [
      ['City and trains', 'Helsinki by day: waterways, bridges and the train arrival board'],
      ['Night traffic', 'Evening traffic on Helsinki’s illuminated streets'],
      ['Winter and trains', 'Snowfall at Oulu station, with a train on the tracks'],
      ['RageCab phone', 'RageCab phone in rainy Helsinki: a train passenger’s prebooking beside a ride request'],
      ['Map of Finland', 'Choosing a starting location on the map of Finland'],
      ['Weather forecast', 'Start screen with a real weather forecast'],
    ],
    navLabel: 'Main navigation', homeLabel: 'The Road Rage Trip home', heroLabel: 'The Road Rage Trip loading artwork',
    introKicker: '01 / THE ANTIHERO', intro: 'Short fuse.<br><span>Supernatural rage.</span>', lead: 'The Road Rage Trip is a top-down taxi game on real Finnish streets. You are its antihero: a cab driver whose rage moves cars out of the way.',
    introText: 'Your passenger is waiting. The whole street is stuck. You aren’t. Build enough rage, hit SPACE, and shout traffic to hell. In the latest version, other cars move straight to the roadside and your path stays clear for at least ten seconds. Even at 210 km/h. No heroic speeches. The meter is running.',
    featureKicker: '02 / UNDER THE HOOD', featureTitle: 'Built for the<br><em>beautifully irritated.</em>', featureIntro: 'Not a backdrop. Roads, weather, pedestrians, and consequences are alive around you.',
    features: [
      ['Real roads, real places', 'Recognize a familiar junction, cut past the park, and find your passenger’s address. Real Finnish streets are your playground.'],
      ['Shout traffic to hell', 'Rage isn’t just a face on your dashboard. It is your superpower. Speeding builds rage; with enough in the tank, SPACE shoves other cars aside. Your rage shout keeps the road clear for at least ten seconds, looking farther ahead the faster you drive. You floor it. They move.'],
      ['The streets are full of other drivers', 'Cars, vans, trucks and buses share the streets with you. Crashes can lead to roadside arguments. Keep your cool – or build enough rage to shout your way through.'],
      ['Eyes on the road', 'A hidden speed camera can catch you just as you start enjoying the speed. Trees sway, leaves fly, and a hard enough crash leaves the taxi smoking and stuck for five seconds.'],
      ['Routes that react', 'Press N or P to open the phone. During an active fare it shows the next turn, distance and street name. When you are free, the same phone shows ride requests.'],
      ['A city that keeps growing', 'Leave familiar streets behind and discover what lies ahead. City streets give way to neighborhoods, forests and waterfront roads. Your next passenger is out there somewhere.'],
      ['Bridges and water', 'Cross the river, follow the waterfront, and find your way over the bridges. The water looks beautiful. Your taxi belongs on dry land.'],
      ['Rain that changes the drive', 'Weather shifts in real time: rain slowly wets the road, puddles splash under your tires, and wet asphalt steals your grip exactly when you need it most.'],
      ['The city lights up at night', 'Streetlights, glowing windows and oncoming headlights cut through the dark. On the night shift, a familiar city shows a different face.'],
      ['Pedestrians with a pulse', 'Residents walk to their own doors, check their phones, sit on benches, or go for a jog – and stumble home from the bar. Keep your eyes open: not everyone walks a straight line.'],
      ['Traffic lights play along', 'Junctions and signals guide both you and every pedestrian around you. Running a red shows up directly in the taxi score.'],
      ['Four Finnish seasons', 'Choose your starting date and time in freelance-driver mode. Snow accumulates on roads and roofs, tires leave tracks and ploughs clear the streets. Spring brings floating ice, summer greenery and autumn colors.'],
      ['Every fare grows your balance', 'The meter runs, the journey continues, and your balance grows. Get your passenger there, collect the fare, and find your next ride.'],
      ['Passengers remember your driving', 'Crashes and reckless driving hurt satisfaction. A fast ride that arrives on time can earn a tip of up to ten euros.'],
      ['Trains run on time', "Real train timetables bring stations to life: trains roll in with headlights blazing, the station announces them, and a passenger with luggage has already booked your ride."],
      ['Weather from the real world', 'Switch on real weather and face the conditions for your chosen place and time. Rain lashes the windshield, frost bites, and slippery roads test your nerve. Your passenger still expects to get there.'],
      ['The tank won’t fill itself', "Fuel burns as you drive. Pull into a gas station, fill up at the pump price, and get back to your fares before the gauge hits empty."],
      ['Underground and upstairs', "Not every passenger waits on a street corner. Take the ramp into a car park and pick up fares underground, with your navigator showing the way."],
      ['RageCab is calling', 'One movable phone handles ride requests and train-passenger prebookings while you are free. Accept a fare and it switches to navigation.'],
      ['Holidays come to town', 'New Year fireworks, Halloween pumpkins and lanterns, and Santas wandering the streets on Christmas Eve follow the game calendar.'],
    ],
    roadmapKicker: "03 / WHAT'S NEXT", roadmapTitle: 'The road continues.<br><em>Chaos grows.</em>', roadmapIntro: "The city isn’t about to make your shift easier. There is more trouble heading for these streets.", roadmapSoon: 'SOON',
    roadmapCards: [
      ['Idiot cyclists', 'Cyclists join the chaos: weaving through traffic, running red lights, and doing exactly what cyclists do best.'],
      ['Police car chases', 'Hidden cameras only go so far. Real police cars will give chase with sirens on, and losing them will take more than a shout.'],
      ['Taxi driver brawls', "When rage doesn't fit in words anymore, step out of the car and settle it the old-fashioned way."],
    ],
    howKicker: '04 / TAKE THE WHEEL', howTitle: 'Know the<br><span>rules.</span><br>Break the calm.', howLead: 'The city is your playground. The score is yours to ruin.',
    controls: ['Drive, brake, steer (arrow keys also work)', 'RageCab phone: 1–3 accept, X declines', 'Rage shout: clear the way', 'Phone: ride requests or navigation', 'Lane assist', 'Speed limiter', 'Traffic-light assist', 'Return the taxi to the road, T resets trip meter', 'Pause, settings, change city', 'Enter or leave the taxi', 'Start or stop the engine', 'Refuel at a gas station', 'Train arrival board'],
    notesKicker: '05 / LATEST VERSION', notesTitle: 'The latest<br><em>version.</em>', notesLead: 'In the latest version, rage clears the road. Group fares and improvements to maps, weather and traffic round out the ride.',
    notes: [
      ['Rage is your superpower', 'The new rage shout moves other cars straight to the roadside and keeps your path clear for at least ten seconds. Clearance reaches ten driving seconds ahead, even at 210 km/h.'],
      ['One fare, several passengers', 'Group fares carry up to four passengers. Children ride with their parent.'],
      ['Bridges, coasts and lakes', 'Clearer bridges, coastlines and islands help you find your way. Get behind the wheel sooner in lake country, too.'],
      ['Light and shadow', 'Building shadows follow the sun, while longer high beams also cover the opposing lane.'],
      ['Another shift, familiar weather', 'Return to the same place and time without a surprise change of weather. Conditions stay more consistent between sessions.'],
      ['A smoother start to your shift', 'Other cars appear at safer distances, and lost drivers find their way back more reliably. Fewer needless obstacles. More driving.'],
    ],
    releaseKicker: 'AVAILABLE / 0.17.1alpha', releaseTitle: 'Your next fare<br>is waiting.', releaseText: 'Download the 0.17.1alpha Windows installer. This is a work-in-progress alpha: bugs and performance issues remain.', releaseButton: 'Download Windows installer',
    scroll: 'SCROLL TO EXPLORE', toggle: 'Switch to Finnish',
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
  document.querySelector('nav').setAttribute('aria-label', t.navLabel);
  document.querySelector('.brand').setAttribute('aria-label', t.homeLabel);
  document.querySelector('.hero-image').setAttribute('aria-label', t.heroLabel);
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
  document.querySelectorAll('.screenshot-grid figure').forEach((figure, index) => {
    figure.querySelector('figcaption').textContent = t.screenshots[index][0];
    figure.querySelector('img').setAttribute('alt', t.screenshots[index][1]);
  });
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
