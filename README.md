# GARO Entity för Home Assistant – beta 4

En HACS-förberedd Home Assistant-integration för GARO Entity. Den använder
[GARO Entity CSMS End User API](https://end-user-api.prod.garo-next-gen.com/docs)
och kan använda separata konton för rollerna `EVDriver` och `Owner`. Den kan även
ansluta till GARO:s lokala HTTPS-API för snabbare mätvärden och tidsstyrd
gruppström.

Det här är en AI-assisterad vidareutvecklad betaversion av
[g60ocR/garo-entity](https://github.com/g60ocR/garo-entity), publicerad under samma
MIT-licens. Tack till originalprojektets skapare för grunden. Detta är ett
fristående communityprojekt och inte en officiell GARO-integration.

## Status och skillnader mot originalet

Version **1.1.0b4** lägger till separata EVDriver-/Owner-konton, start/stopp,
lokalt HTTPS-API, schemalagd gruppström, svenska texter och diagnostik.
Autentisering och sensorhantering har omarbetats. Sensorurvalet är mer begränsat
än i originalet; alla tidigare detaljsensorer finns inte med.

De 31 medföljande enhetstesterna täcker bland annat autentisering, parsning,
separata lokala anslutningar och schemaläggning. Vid ett begränsat driftprov
2026-11-16 bekräftade användaren att start av laddning och lokal avläsning i
Home Assistant fungerade. Laddboxens verkliga svar under laddning tolkades också
korrekt av integrationens parser. Tidigare nollvärden kunde inte reproduceras;
orsaken är inte fastställd. Stopp, lastbalanserarens schema och återhämtning efter
avbrott återstår att verifiera i drift. Börja med manuell installation och en laddbox. Testerna använder simulerade svar och bevisar inte
att alla kontoroller, firmwareversioner eller styrkommandon fungerar i drift.

## Funktioner

- Starta och stoppa laddningen med en riktig Home Assistant-switch.
- Visa aktuell OCPP-status: `Available`, `Preparing`, `Charging`, med flera.
- Visa energin i pågående eller senast avslutade laddning i kWh.
- Visa laddningens start- och sluttid.
- Visa total importerad energi, aktuell effekt och erbjuden ström när molnet har
  färska mätvärden.
- Ändra `GaroOwnerMaxCurrent` mellan 6 och 32 A för Owner-konton.
- Använd ett separat EVDriver-konto för start/stopp och ett valfritt Owner-konto
  för konfiguration och utökade mätvärden.
- Läsa lokal fasström, total effekt och `GaroConnectionGroupMaxCurrent`.
- Begränsa anslutningsgruppens ström under valda tider, veckodagar och månader.
- Automatisk tokenförnyelse, återinloggning och diagnostik med känsliga värden
  maskerade.
- Egen ikon/logotyp samt svenska och engelska namn i Home Assistant.

Senaste laddningens energi beräknas enligt GARO:s transaktionsmodell:

```text
(meter_stop - meter_start) / 1000 = kWh
```

`meter_start` och `meter_stop` är heltal i Wh enligt API-modellen. Under en
pågående laddning används senaste energimätarställningen om den finns.

## Installation för test

1. Kopiera mappen `custom_components/garo_entity` till
   `/config/custom_components/garo_entity` i Home Assistant.
2. Om den äldre `garo_entity`-integrationen redan finns: ersätt dess mapp. De två
   varianterna kan inte vara installerade samtidigt eftersom de har samma domän.
3. Starta om Home Assistant.
4. Öppna **Inställningar → Enheter och tjänster → Lägg till integration**.
5. Sök efter **GARO Entity** och ange EVDriver-kontot som ska få starta och stoppa
   laddningen.
6. Ange även Owner-kontot om du vill läsa och styra Owner-konfiguration. De två
   kontona måste ha åtkomst till samma laddbox.
7. Om du redan har ett fungerande script: använd exakt dess `CLIENT_ID` i
   respektive Cognito-fält. Standardvärdet kommer från GARO:s API-dokumentation,
   men GARO har använt fler än en appklient.

Ett befintligt konto kan kompletteras utan att entiteterna behöver tas bort. Välj
**Konfigurera om** på integrationsposten och fyll i Owner-kontot.

Vid uppgradering återanvänds entitets-id:n för anslutningsstatus, laddenergi,
start/sluttid och maximal laddström. Äldre detaljsensorer som inte längre skapas
kan ligga kvar som otillgängliga i entitetsregistret och kan tas bort efter att
betan har verifierats.

Standardintervallet är 60 sekunder. Status och transaktioner läses varje intervall,
mätvärden var femte minut och konfiguration var femtonde minut. Intervallet kan
ställas mellan 30 och 900 sekunder vid installationen.

## HACS

Projektet innehåller `hacs.json` och rätt katalogstruktur. Lägg till
`https://github.com/fiddexx/ha-garo-entity` som ett anpassat repository i HACS,
av typen **Integration**. Detta innebär inte att projektet är godkänt i HACS
standardkatalog. Manuell installation rekommenderas under betatestningen.

Rapportera problem med denna version i
[det här projektets ärenden](https://github.com/fiddexx/ha-garo-entity/issues),
inte i originalprojektet. Bifoga aldrig lösenord eller omaskerad diagnostik.

## Entiteter per laddbox

| Typ | Entitet | Kommentar |
| --- | --- | --- |
| Switch | Laddning | Startar eller stoppar en transaktion via moln-API:t. |
| Sensor | Anslutningsstatus | OCPP-status för kontakt 1. |
| Sensor | Pågående eller senaste laddning | Sessionens energi i kWh. |
| Sensor | Laddning startade/avslutades | Tidsstämplar från transaktionen. |
| Sensor | Total importerad energi | Kan användas i energipanelen när värdet finns. |
| Sensor | Laddeffekt | Senaste molnvärdet i W. |
| Sensor | Tillgänglig laddström | `Current.Offered` i A. |
| Number | Maximal laddström | `GaroOwnerMaxCurrent`, endast för Owner-konton. |

## Tre anslutningar i beta 4

| Anslutning | Uppgift |
| --- | --- |
| GARO-molnet, EVDriver | Start/stopp, laddstatus och transaktioner. Kontot måste ha tillgång till laddboxen. |
| Laddboxens lokala API, GaroCU | Skrivskyddad avläsning av effekt och fasströmmar. |
| Lastbalanserarens lokala API, GaroLI | Separata fasströmmar, effekt och gruppgräns. Endast denna anslutning får köra gruppströmsschemat. |

Owner är valfritt för molnkonfiguration. Lokala anslutningar ersätter inte
EVDriver-inloggningen. Lokal laddstatus och lokal sessionsenergi är ännu inte
implementerade; dessa visas fortsatt från molnet.

Öppna **Konfigurera** för att aktivera respektive lokal anslutning. Ange en
separat adress och inloggning för laddboxen och lastbalanseraren. Använd endast
värdnamn/IP eller bas-URL, utan lösenord eller `/status/energy-meter` i adressen.
Lösenorden anges i egna fält; lämna ett lösenordsfält tomt för att behålla det
sparade lösenordet. TLS-verifiering kan stängas av för självsignerade certifikat.

Lokala mätvärden visas under separata enheter **GARO Entity Charger (local)**
och **GARO Entity Balance (local)**. De blandas inte med molnets laddenergi.
Varje lokal enhet uppdateras självständigt med integrationens uppdateringsintervall.
Efter lyckad uppstart fortsätter lokal polling även om molnet inte svarar.
**Vid uppstart krävs fortfarande en lyckad molnanslutning** för att upptäcka
laddboxarna innan integrationen kan laddas.

### Uppgradering från beta 3

Den tidigare lokala adressen behålls i lastbalanserarens fält. Kontrollera den:
om den pekade på en laddbox ska uppgifterna i stället anges i laddboxens fält.
Befintliga lokala entitets-ID:n behålls för den äldre anslutningen. Har de använts
för laddboxens mätning behöver berörda automationer kontrolleras när rollen ändras.

Schemat skriver **ingenting förrän du bekräftat att adressen är lastbalanserarens**
och aktiverat både anslutningen och schemat. Tidigare schemavärden bevaras, men
bekräftelsen krävs efter uppgraderingen. Inloggningar flyttas från options till
config entry-data och maskeras i integrationens diagnostik.

### Schema för lastbalanseraren

- Standardgräns: **55 A** som förvalt värde.
- Höglastgräns: **20 A** som förvalt värde.
- Tid: **07:00–20:00**, måndag–fredag.
- Månader: januari–mars och november–december.

Kontrollera gränserna mot din installation innan aktivering. Schemat skriver
endast när en färsk avläst gräns skiljer sig från målet. Gränsen läses tillbaka
efter skrivning; ett lyckat HTTP-svar räcker inte för att rapportera en ändring.
Vid läsfel skickas inget nytt kommando. Laddboxens lokala anslutning får aldrig
skriva denna gräns eller skicka start/stopp.

## Moln och lokalt API bör ha olika roller

| Källa | Lämplig användning |
| --- | --- |
| GARO-molnet | Start/stopp, kontaktstatus, transaktioner och senaste laddningens kWh. |
| Laddboxens lokala API (`GaroCU-…`) | Snabba livevärden för effekt, ström och total energi. |
| Entity Balance (`GaroLI-…`) | Fastighetens/fördelningens fasvärden, DLM-status och gruppgräns. |

Följande projekt är fortsatt användbara om man bara vill ha lokala mätvärden utan
molnkonton:

- [GARO Entity Charger Meter](https://github.com/JanJoh/Garo-entity-charger-meter-ha)
- [GARO Entity Balance Meter](https://github.com/JanJoh/Garo-entity-balance-meter-ha)

## Viktigt om strömgränser

`GaroConnectionGroupMaxCurrent` är gruppens/DLM-installationens maximala ström i
**ampere**. Det är inte kW och definitivt inte kWh. Parametern kan påverka
installationsskydd och lastbalansering. Därför visas den som en skrivskyddad
sensor och ändras endast av det uttryckligen aktiverade administratörsschemat.

Använd aldrig en standardgräns som är högre än vad elanläggning, kablage,
lastbalansering och säkringar är dimensionerade för. Integrationens intervall
6–63 A är en teknisk gräns, inte ett besked om vad installationen tål.

För normal begränsning av en enskild laddbox används i stället
`GaroOwnerMaxCurrent`, 6–32 A. På trefas motsvarar exempelvis 16 A ungefär 11 kW,
men bilen, nätspänningen och lastbalanseraren avgör den faktiska effekten.

## Felsökning

Om inloggningen misslyckas, kontrollera först att `CLIENT_ID` är identiskt med
värdet i ett script som faktiskt kan logga in. Integrationen använder ett direkt,
asynkront Cognito-anrop och behöver därför inte `boto3`. I Home Assistants logg
visas en säker felkod som exempelvis `NotAuthorizedException`; lösenord och token
loggas inte.

Aktivera detaljerad loggning tillfälligt:

```yaml
logger:
  logs:
    custom_components.garo_entity: debug
```

Ladda därefter ner diagnostiken från integrationens meny i Home Assistant. Lösenord,
användarnamn och RFID-/ID-token maskeras. Lägg aldrig autentisering, lokala lösenord
eller fullständiga tokens i ett publikt GitHub-ärende.

## Begränsningar

- Moln-API:t kräver internet och kan ligga efter den lokala laddboxen.
- Kommandon skickas asynkront (`response_required=false`) och statusen uppdateras
  efteråt; ett lyckat HTTP-svar är inte samma sak som att bilen faktiskt började
  ladda.
- `GaroOwnerMaxCurrent` kräver Owner-rättighet. EVDriver-konton får fortfarande
  start/stopp och de sensorer de har åtkomst till.
- Det lokala effektschemat fungerar bara när Home Assistant kan nå enheten på
  dess LAN-adress. Vid kommunikationsfel behålls senast satta gräns i GARO-enheten.
- Integrationen har byggts mot API-version `0.1` och bör verifieras mot flera
  firmware- och kontotyper innan bred publicering.

## Ursprung och licens

Denna beta är en omarbetning av MIT-projektet
[g60ocR/garo-entity](https://github.com/g60ocR/garo-entity). Se `LICENSE`.
