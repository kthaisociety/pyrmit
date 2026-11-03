# Öppna kartlager med gällande detaljplaner, alla 290 kommuner

Kartläggning gjord 2026-11-03. Frågan: publicerar kommunen ett **maskinläsbart lager med planpolygoner**, och har varje polygon en **länk till planhandlingarna**? Det är det minsta vi behöver för att slippa mejla kommunen.

Data per kommun finns i [kommun-planlager.csv](kommun-planlager.csv) och [kommun-planlager.json](kommun-planlager.json).

## Resultat

| Status | Antal | Betydelse |
|---|---|---|
| **A** | 152 | Öppet lager med polygoner **och** fält med dokumentlänk. Går att använda direkt. |
| **B** | 35 | Öppet lager med polygoner men utan dokumentlänk (ofta akt eller plannummer finns). Kräver att vi hittar dokumenten själva, via akten eller ett URL-mönster. |
| **D** | 75 | Kartvisare eller GIS-server finns, men planlagret går inte att hämta maskinellt (bara bild/WMS utan GetFeatureInfo, token-skyddat, eller inget planlager alls). |
| **E** | 28 | Inget hittat. Oftast bara PDF-listor på webben. |

**187 av 290 kommuner (64 %) har polygoner som går att hämta utan att fråga.** 152 av dem har dokumentlänk i lagret. Siffrorna är en undre gräns: statusen D/E betyder "hittade inte", inte "finns inte".

Mejl behöver bara gå till **103 kommuner** (D + E), och för D-kommunerna är frågan konkret: "ni har lagret i er kartvisare, kan ni exponera det som WFS/REST eller skicka en export?"

## Hur kartläggningen gjordes

1. **Kataloger.** Sveriges dataportal (hela DCAT-dumpen, 23 730 dataset), geodata.se (CSW) och ArcGIS Online (global sökning + varje kommuns egen org). Dataportalen gav bara ~15 kommuner, geodata.se nästan inget. Kommunerna registrerar inte sina planlager i kataloger.
2. **Automatisk sondering.** För alla 290 kommuner provades ~40 värdnamn (kartor., karta., gis., geodata., kartportal., webbkarta., geoportal., gisportal. …) mot ArcGIS REST (`/arcgis|/server|/mapping/rest/services`) och WFS GetCapabilities på http och https. Hittade servrar crawlades, planlager identifierades på namn, och varje lager räknades och ett exempelobjekt hämtades. Det gav 146 kommuner med server, 114 med verifierat planlager.
3. **Manuell efterforskning.** De 168 kommuner som återstod undersöktes av fem parallella agenter: webbsökning, kommunens sida om detaljplaner, kartvisarens konfiguration (Origo-json, ArcGIS-appkonfig, Hajk-API, qgis2web) och curl mot bakomliggande tjänst. Status A/B sattes bara när ett objekt faktiskt hämtats.
4. **Stickprov.** Göteborg, Lund, Krokom m.fl. kontrollerades i efterhand.

Skripten ligger i sessionens scratchpad, inte i repot: `dataportal.py`, `parse_rdf.py`, `probe.py`, `crawl.py`, `consolidate.py`.

## Mönster som är värda att känna till

- **Leverantören avgör allt.** ArcGIS Server/Enterprise (Esri, ofta via Geosecma eller Gaida) och GeoServer/QGIS Server bakom Origo eller Hajk ger nästan alltid öppna REST/WFS. **Sokigo Spatial Suite / SpatialMap** (CSM) och **Aveki myCarta** ger i praktiken bara WMS-bilder, och planlagren är `queryable=0`. Av de 95 D/E-kommunerna i den manuella genomgången nämner 41 Sokigo/Geosecma/Spatial Suite och 19 Aveki myCarta.
- **Samverkan täcker många små kommuner på en gång.** Ett lager, flera kommuner: RIGES hos Sundsvall (Sundsvall, Timrå, Ånge, Nordanstig, Härnösand, Örnsköldsvik), Samhällsbyggnad Bergslagen (Hällefors, Ljusnarsberg, Nora, Lindesberg), Sydnärke (Lekeberg, Laxå, Askersund), VDMB (Norberg, Fagersta, Avesta), Sandviken/VGS (Sandviken, Ockelbo, Hofors), Tranås GeoServer (Tranås, Ödeshög, Ydre, Kinda, Boxholm), Göliska (Vara, Essunga, Skara), gisportal.perstorp.se / gts.klippan.se (Perstorp, Bjuv, Svalöv, Klippan, Åstorp, Örkelljunga), kartportal.unikom.se (Osby, Östra Göinge), kartportal.se (Staffanstorp, Kävlinge), geoinfomittskane.se (Höör, Hörby), Kumla (Kumla, Hallsberg), Mariestad (Mariestad, Töreboda, Gullspång).
- **Länkfältet är inte alltid en URL.** Vanliga varianter: HTML-ankare (`<a href=...>`), bara filnamn som ska sättas ihop med ett basmönster (Tranås-servern, Falköping, Kungsbacka, Mora/Orsa/Älvdalen), Geosecma `DocumentLinks` som pekar på portal-items, och interna UNC-sökvägar (`\\server\...`) som är oanvändbara (Vaggeryd, Hylte, Smedjebacken, Bollnäs, Piteå, Hervar). CSV:n har kolumnen `url_example` så att man ser vilket.
- **Stadsplaner och byggnadsplaner** ligger ofta i samma lager som detaljplaner med ett typfält, ibland i separata lager (Markaryd, Älmhult, Göteborg `typ`).
- **Storstäderna:** Stockholm har inget öppet planlager alls (dataportalen kräver nyckel, openstreetgs saknar planer). Göteborg har WFS med URL (8 037 objekt inkl. program, 1 417 DP). Malmö har ArcGIS med LMAKT och URL. Uppsala som tidigare.
- **Bulk vs punkt.** Några kommuner (Södertälje, Rättvik) svarar bara på WMS GetFeatureInfo per punkt, inte på WFS-hämtning av hela lagret. De är markerade A med anteckning, men kräver ett annat hämtsätt än snapshot.

## Rekommendation för nästa steg

1. **Ta in A-kommunerna i batchar efter plattform**, inte efter kommun: en ArcGIS-adapter (REST `query` med paginering), en WFS-adapter (GeoServer/QGIS Server) och en för statiska GeoJSON (qgis2web). Det täcker nästan alla 152.
2. **B-kommunerna:** använd akten eller plannumret för att slå upp PDF:en. I flera fall finns ett förutsägbart URL-mönster (anteckningar i CSV:n).
3. **Mejla D före E.** D-kommunerna har redan datat i en kartvisare och ett konkret svar är lätt: "exportera lagret eller slå på WFS". Mejlet kan nämna vilken visare vi sett.
4. **Kontrollera licens innan publicering.** Få lager anger licens. Dataportal-posterna är CC0 (Gävle, Umeå, Lidingö m.fl.), men de flesta ArcGIS-servrar säger inget. Det måste in i mejlet eller i en separat fråga.

## A. Öppet lager med dokumentlänk (152)

| Kod | Kommun | Typ | Endpoint | Lager | Antal | Länkfält | Akt-fält | Anteckning |
|---|---|---|---|---|---|---|---|---|
| 0120 | Värmdö | wfs | https://karta.varmdo.se/geoserver/ows | intern_db:vy_gallande_detaljplaner_y | 559 | lank_intern, lank_extern, lank | planbeteckning |  |
| 0126 | Huddinge | wfs | https://gd-huddinge.sokigohosting.com/public-maps/Oppnadata/MBF?token=… | qgs:dp_plan (Detaljplaner) | 1377 | dp_planhandlingar | dp_plannummer, dp_aktnummer | Hittad via dataportal.se-posten 'Detaljplaner' (metadatakatalog.huddinge.se). QGIS Server … |
| 0136 | Haninge | wfs | https://karta.haninge.se/services/karta/ows?SERVICE=WFS&VERSION=1.1.0&… | planersutbredning (Planer) | 569 | lank_dokument_ext | planbet, planbet_lokal, planbet_gm, planbet_gm_lokal | Origo-konfig på /origo/index.json. QGIS Server WFS 1.1.0 (2.0.0 misslyckades med TYPENAMES… |
| 0139 | Upplands-Bro | arcgis | https://kartportalen.upplands-bro.se/arcgis/rest/services/NyaExternaKa… | NyaExternaKartan/Detaljplaner_NyKommunka… | 221 | Lank1, Lank2 |  |  |
| 0163 | Sollentuna | arcgis | https://geodata.sollentuna.se/arcgis/rest/services/Planmosaik/MapServe… | Planmosaik/Planområde | 559 | DocumentLinks, DocumentLinksHtml |  |  |
| 0181 | Södertälje | wms | https://karta.sodertalje.se/qgs_extern/templet/sbkgeoinfo?SERVICE=WMS&… | gallande_planer (Gällande detaljplaner) |  | dp_planhandlingar, planfil | dp_plannummer | OBS: WMS GetFeatureInfo (punktfråga) – ingen WFS-typename publicerad, så ingen bulk-nedlad… |
| 0182 | Nacka | wfs | https://karta.nacka.se/geoserver/ows | nacka:detaljplaner_gallande | 993 | url | aktbeteckning |  |
| 0183 | Sundbyberg | arcgis | https://gis.sundbyberg.se/arcgis/rest/services/Gallande_detaljplaner2/… | Gallande_detaljplaner2/Gällande detaljpl… | 268 | LANK, LANK2 | PLANNR, DNR | länkfält finns men exempelvärdet är relativt/internt: (Saknas) |
| 0330 | Knivsta | arcgis | https://kartor.knivsta.se/arcgis/rest/services/Plan/planoversikt_syfte… | Plan/planoversikt_syfte/Gällande detaljp… | 144 |  | AKTBETECKNING, DIARIENUMMER, AKTUALITET | länkfält finns men exempelvärdet är relativt/internt:  |
| 0380 | Uppsala | arcgis | https://kartportal.uppsala.se/mapping/rest/services/nUrban/Detaljplane… | nUrban/Detaljplaner_Urban/Gällande detal… | 1417 | UrlDokument | Aktbeteckning |  |
| 0381 | Enköping | wfs | https://karta.enkoping.se/geoserver/ena_extern/ows?service=WFS&version… | ena_extern:detaljplaner (Gällande detalj… | 551 | http | lmakt, plannr, planbeteck | Origo index.json -> GeoServer workspace ena_extern (själva /geoserver/ows ger 401, men wor… |
| 0428 | Vingåker | arcgis | https://karta.vingaker.se/server/rest/services/Samh%C3%A4llsbyggnad/De… | Detaljplaner | 159 | Länk | Planbet, Plannr | ArcGIS Enterprise på karta.vingaker.se (/server/rest, inte /arcgis). Länk -> https://asset… |
| 0481 | Oxelösund | arcgis | https://karta.oxelosund.se/arcgis/rest/services/Gaida_Oxelosund/Bygga_… | Gaida_Oxelosund/Bygga_och_bo/Detaljplane… | 217 | plankarta, lank_karta, lank_text |  | länkfält finns men exempelvärdet är relativt/internt: dp1768 |
| 0482 | Flen | arcgis | https://gis.flen.se/arcgis/rest/services/Detaljplaner/MapServer/0 | Detaljplaner/Detaljplaner och områdesbes… | 359 | Plankarta | LM_beteckning, Plannr, AKTUALITETSDATUM | länkfält finns men exempelvärdet är relativt/internt: BE 4 Plankarta.pdf |
| 0484 | Eskilstuna | arcgis | https://geo.eskilstuna.se/arcgis/rest/services/GAIDA_Detaljplaner_laga… | GAIDA_Detaljplaner_laga_kraft_MIL1/Eget … | 49 | DocumentLinks, DocumentLinksHtml |  |  |
| 0486 | Strängnäs | arcgis | https://geodata.strangnas.se/arcgis/rest/services/temakarta_sol_vind_/… | temakarta_sol_vind_/Gällande detaljplane… | 607 | lank | diarienr |  |
| 0509 | Ödeshög | wfs | https://karta.tranas.se/geoserver/ows?service=WFS&version=2.0.0&reques… | odeshogext:karta_detaljplaner-gallande | 79 | link | namn | link är relativt filnamn (t.ex. 05-TRE-181.pdf) -> https://karta.tranas.se/odeshog/kommunk… |
| 0512 | Ydre | wfs | https://karta.tranas.se/geoserver/ows?service=WFS&version=2.0.0&reques… | ydre_kommunkarta:karta_detaljplaner-gall… | 94 | link | namn | link relativt (akt_05-TOR-278.VOL2.pdf) -> https://karta.tranas.se/Ydre/kommunkarta/docs/d… |
| 0513 | Kinda | wfs | https://karta.tranas.se/geoserver/ows?service=WFS&version=2.0.0&reques… | kinda_kommunkarta:karta_detaljplaner-gal… | 288 | link | namn | link relativt (akt_0513-P08_4.pdf) -> https://karta.tranas.se/kinda/kommunkarta/docs/detal… |
| 0560 | Boxholm | wfs | https://karta.tranas.se/geoserver/ows?service=WFS&version=2.0.0&reques… | boxholm_kommunkarta:karta_detaljplaner-g… | 128 | link | namn | link relativt (akt_05-MAL-390.VOL2.pdf) -> https://karta.tranas.se/boxholm/kommunkarta/doc… |
| 0562 | Finspång | arcgis | https://ext-gisapp.finspang.se/arcgis/rest/services/Externakartan/Deta… | Detaljplaner Finspång | 295 | Länk | PLANBET, Planbet_Finspang | Länk -> portal item data (PDF 200), t.ex. .../portal/sharing/rest/content/items/<id>/data.… |
| 0583 | Motala | arcgis | https://utility.arcgis.com/usrsvcs/servers/5e57cc208ce84edfadad188b306… | PUBLIC_SERVICES/Ändring av detaljplan | 54 | DOCLINK |  |  |
| 0584 | Vadstena | arcgis | https://gisportal.vadstena.se/arcgis/rest/services/PoB/Detaljplaner_gä… | PoB/Detaljplaner_gällande/Eget temalager | 12 | DocumentLinks, DocumentLinksHtml |  |  |
| 0586 | Mjölby | arcgis | https://gis.mjolby.se/arcgis/rest/services/Bygga__Bo_och_Miljö1/MapSer… | Bygga__Bo_och_Miljö1/Detaljplaner | 442 | Lank_plankarta, Lank_dokument |  |  |
| 0617 | Gnosjö | arcgis | https://gisportal.gnosjo.se/arcgis/rest/services/Plan/Detaljplanoversi… | Plan/Detaljplanoversikt/Detaljplaner | 226 | ExternLänk |  |  |
| 0642 | Mullsjö | wfs | https://karta.sweco.se/geoserver/Mullsjö/ows?service=WFS&version=1.1.0… | Mullsjö:karta_detaljplaner-gallande | 166 | link | namn, beskr | Origo-visare hostad av Sweco. WFS GeoServer. 'link' är filnamn (t.ex. 16-NYK-740.pdf) rela… |
| 0643 | Habo | arcgis | https://karta.habokommun.se/server/rest/services/GEOSECMA/Detaljplaner… | GEOSECMA/Detaljplaner/Eget temalager | 163 | DocumentLinks, DocumentLinksHtml |  |  |
| 0662 | Gislaved | arcgis | https://kartor.gislaved.se/arcgis/rest/services/Kommunkarta/Bygga_och_… | Kommunkarta/Bygga_och_bo/Gällande detalj… | 450 |  |  | länkfält finns men exempelvärdet är relativt/internt:  |
| 0665 | Vaggeryd | arcgis | https://geodata.vaggeryd.se/arcgis/rest/services/Temakartor_AoL/Detalj… | Temakartor_AoL/Detaljplaner_1/Planområde | 35 | DocumentLinks, DocumentLinksHtml |  | länkfält finns men exempelvärdet är relativt/internt: F:\Kansli\Fysisk planering 3.1\3.1 P… |
| 0680 | Jönköping | arcgis | https://gis.jonkoping.se/arcgis/rest/services/kommunatlas/Kommunatlas_… | kommunatlas/Kommunatlas_Bygga_Bo_och_Mil… | 1547 | link | LMAkt, EgenAkt |  |
| 0683 | Värnamo | arcgis | https://karta.varnamo.se/arcgis/rest/services/Kartor_och_mätning/Karto… | Gällande detaljplaner | 475 | URL | PLANNUMMER, PLANOMRADE | URL pekar på https://gis.varnamo.se/Kopplade_Dokument/Detaljplan/<plan>.pdf. Lager 0 = upp… |
| 0687 | Tranås | wfs | https://karta.tranas.se/geoserver/wfs?service=WFS&version=1.1.0&reques… | tranas_kommunkarta:karta_detaljplaner-ga… | 425 | link | namn, beskr | Origo + GeoServer (delad server för Tranås/Ydre/Kinda/Boxholm/Ödeshög). 'link' = filnamn (… |
| 0761 | Lessebo | arcgis | https://gis.lessebo.se/arcgis/rest/services/Detaljplankarta_för_Lesseb… | Detaljplankarta_för_Lessebo/Detaljplaner | 221 | pdf, länk1 | Akt_nr | länkfält finns men exempelvärdet är relativt/internt: 1 |
| 0763 | Tingsryd | arcgis | https://geodata.tingsryd.se/server/rest/services/planer/MapServer/371 | planer/gällande planer | 424 | L_ñnk_url |  |  |
| 0764 | Alvesta | arcgis | https://argo.alvesta.se/arcgis/rest/services/Detaljplan_ytor/MapServer… | Länkade_planer | 387 | Descr | Plannr_L30, Name | Descr = https://geosecma-web.alvesta.se/Alvesta/<plannr>.pdf. Laga_kra29 är textdatum (YYY… |
| 0765 | Älmhult | arcgis | https://geodata.almhult.se/server/rest/services/Detaljplaner_geodatapo… | Detaljplaner_geodataportal/Tomtindelning… | 205 | PLANDOKUMENT_LANK, PLANKARTA |  |  |
| 0780 | Växjö | arcgis | https://gis2.vaxjo.se/arcgis/rest/services/Ovrigt/Detaljplaner/MapServ… | Ovrigt/Detaljplaner/Planområde | 2142 |  | AKTBETECKNING | länkfält finns men exempelvärdet är relativt/internt:  |
| 0821 | Högsby | arcgis | https://arcgis.hogsby.se/server/rest/services/Detaljplaneomraden_ref/F… | Detaljplaneomraden_ref/Detaljplaneomrade… | 133 | LankTillPlan |  |  |
| 0834 | Torsås | arcgis | https://kartportal.torsas.se/arcgis/rest/services/bygg_miljo2/DP_alla/… | bygg_miljo2/DP_alla/Planområde | 141 | DocumentLinks, DocumentLinksHtml |  |  |
| 0840 | Mörbylånga | arcgis | https://karta.morbylanga.se/arcgis/rest/services/Bygglov_extern/MapSer… | Bygglov_extern/Gällande detaljplaner | 381 | sde_plan_miljo.GNG.extrainformationgallandeplaner.URL, sde_plan_miljo.GNG.extrainformationgallandeplaner.lank, sde_gsd.GNG.plan_yta_ny.Lank |  | länkfält finns men exempelvärdet är relativt/internt:  |
| 0861 | Mönsterås | arcgis | https://gis.monsteras.se/server/rest/services/Kommunkarta_20230711/Map… | Kommunkarta_20230711/Planområde | 143 | DocumentLinks, DocumentLinksHtml |  |  |
| 0880 | Kalmar | arcgis | https://karta.kalmar.se/ags/rest/services/Plan/Detaljplaner/MapServer/… | Plan/Planområde | 39 | DocumentLinks, DocumentLinksHtml |  |  |
| 0881 | Nybro | arcgis | https://gisext.nybro.se/server/rest/services/Fysisk_planering_och_bygg… | Fysisk_planering_och_byggande/FPB_Gallan… | 439 | Lank_1, Lank_2, Lank_3, Lank_4 | Plannr |  |
| 0883 | Västervik | arcgis | https://geodata.vastervik.se/arcgis/rest/services/Information/planytor… | Information/planytor/Ändring av detaljpl… | 8 | sde_vvik_plan_ovrigt.GNG.AktNr.Hyperlink1, sde_vvik_plan_ovrigt.GNG.AktNr.LST_aktnr_lank, sde_vvik_plan_ovrigt.GNG.AktNr.Plankarta_hemsidan, sde_vvik_plan_ovrigt.GNG.AktNr.Plankarta_hemsidan_andring | sde_vvik_plan_ovrigt.GNG.AktNr.OBJECTID, sde_vvik_plan_ovrigt.GNG.AktNr.RefName, sde_vvik_plan_ovrigt.GNG.AktNr.Text, sde_vvik_plan_ovrigt.GNG.AktNr.TxtMemo | länkfält finns men exempelvärdet är relativt/internt:  |
| 0885 | Borgholm | arcgis | https://portal.borgholm.se/arcgis/rest/services/Bygga_Bo/Detaljplaner/… | Antagna detaljplaner | 375 | Lank_plank, Planbeskr | PLANBET, EXTERNID, Akt_BHLM, PLNAMN | FeatureServer. Länkar till https://kommunkarta.borgholm.se/Plankarta/<akt>.pdf och /Planbe… |
| 0980 | Gotland | arcgis | https://geo.gotland.se/arcgis/rest/services/2025_VA_kapacitet_ver_1_4_… | 2025_VA_kapacitet_ver_1_4_MIL1/Detaljpla… | 961 | DocumentLinks, DocumentLinksHtml |  |  |
| 1080 | Karlskrona | arcgis | https://geoportal.karlskrona.se/arcgis/rest/services/MSF/Planmosaik/Fe… | MSF/Planmosaik/Planstatus (alla) | 836 | URLPlanensHemsida, URLPlankarta, URLPlanbeskrivning | Diarienummer_DetaljplanensID, Kontaktperson, Kontaktperson2 |  |
| 1082 | Karlshamn | wfs | https://karta.karlshamn.se/maps/Origo/Detaljplaner?SERVICE=WFS&VERSION… | qgs:Gallande_planer | 498 | URL_dokume, URL_karta | Aktnummer, EXTERNID, Id | Origo + QGIS Server WFS. URL_karta/URL_dokume = https://mapweb.karlshamn.se/plandoc/<id>/<… |
| 1083 | Sölvesborg | arcgis | https://map.solvesborg.se/arcgis/rest/services/Detaljplaner_och_område… | Detaljplaner_och_områdesbestämmelser/Det… | 341 | Links_1 |  |  |
| 1230 | Staffanstorp | arcgis | https://kartportal.se/gis/rest/services/stp_pub_detaljplanering/MapSer… | Antagna planer | 204 | URL_Beskrivning, URL_Plankarta, URL_GESTALTNINGSPROGRAM | PLANBET, LM_ID, STP_ID, Planrubrik | Länkar till https://kartportal.se/staffanstorp/Dokument/Detaljplaner_stp/<akt>.pdf. BDAT/L… |
| 1231 | Burlöv | arcgis | https://geodata.burlov.se/arcgis/rest/services/Detaljplaner/Detaljplan… | Detaljplaner/Detaljplaner_2024/Gällande … | 221 | Link_2 |  |  |
| 1233 | Vellinge | arcgis | https://kartor.vellinge.se/arcgis/rest/services/Extern_karta/DPL/MapSe… | Extern_karta/DPL/Gällande planer | 398 | Plankarta |  |  |
| 1260 | Bjuv | arcgis | https://gisportal.perstorp.se/arcgis/rest/services/Bjuv/Planytor_för_p… | Gällande detaljplaner | 279 | URL1, URL2 | planbet, externid, BjuvsPlan, plnamn | URL1 = https://gisportal.perstorp.se/dokument/Bjuv/Detaljplaner/PDF/<akt>.pdf. Lager 1 = p… |
| 1261 | Kävlinge | arcgis | https://kartportal.se/gis/rest/services/kav_pub_planering/MapServer/29… | Gällande plankarta + planbeskrivning | 335 | URLPlanbeskrivning, URLPlankarta, URLPlanprogram, URLBilagor, URLGESTALTNINGSPROGRAM | PLANBET, LM_ID, PLNAMN | Länkar till https://kartportal.se/kavlinge/Dokument/Detaljplaner/<akt>_plankarta.pdf m.fl.… |
| 1262 | Lomma | arcgis | https://gis.lomma.se/arcgis/rest/services/Bygglovskarta/MapServer/17 | Bygglovskarta/Planområde | 26 | DocumentLinks, DocumentLinksHtml |  |  |
| 1263 | Svedala | arcgis | https://maps.svedala.se/arcgis/rest/services/SEPlan/Detaljplaner/MapSe… | SEPlan/Detaljplaner/Gällande detaljplane… | 197 | HOTLINK |  |  |
| 1264 | Skurup | arcgis | https://services-eu1.arcgis.com/2D8y3RBcrHZsGMzp/arcgis/rest/services/… | Skurupkartan/Detaljplaner | 232 | plankarta | plannr |  |
| 1266 | Hörby | arcgis | https://karta.geoinfomittskane.se/arcgis/rest/services/Detaljplan/Deta… | Gällande detaljplan | 551 | Link | externid, planbet_historisk, plnamn | Link = https://karta.geoinfomittskane.se/DocsOnline/Detaljplaner/Horby/<fil>.pdf. Lager 10… |
| 1267 | Höör | arcgis | https://services2.arcgis.com/XcHB8YVJHmlQKJsZ/arcgis/rest/services/Det… | Detaljplaner_Hoor_extern_backup_WFL1/Gäl… | 287 | URL |  |  |
| 1270 | Tomelilla | wfs | https://kartor.tomelilla.se/geoserver/ows | geostore:detaljplaner | 201 | plankarta_mycarta, url, plankarta |  |  |
| 1272 | Bromölla | arcgis | https://map.bromolla.se/arcgis/rest/services/Detaljplaner/Detaljplaner… | Detaljplaner/Detaljplaner_Gallande/Eget … | 4 | DocumentLinks, DocumentLinksHtml |  | länkfält finns men exempelvärdet är relativt/internt:  |
| 1275 | Perstorp | arcgis | https://gisportal.perstorp.se/arcgis/rest/services/Bjuv/Planytor_för_p… | Bjuv/Planytor_för_publicering_externa_we… | 279 | URL1, URL2 |  |  |
| 1276 | Klippan | arcgis | https://gts.klippan.se/arcgis/rest/services/Klippan/Klippan_Gallande_D… | Planområde | 161 | DocumentLinks | Name, RegistrationNumber, DocumentName | DocumentLinks innehåller en eller flera URL:er (radbrutna med \r\n) till https://gisportal… |
| 1277 | Åstorp | arcgis | https://gts.klippan.se/arcgis/rest/services/Astorp/Planytor_Astorp/Map… | Planytor_Astorp | 327 | URL1, URL2 | planbet, externid, plnamn, Doknamn | URL1 = https://gisportal.perstorp.se/dokument/Åstorp/Detaljplaner/PDF/<akt>.pdf. Kommunsid… |
| 1280 | Malmö | arcgis | https://gis.malmo.se/arcgis/rest/services/op/OP2023_Underlag/MapServer… | op/OP2023_Underlag/Detaljplaner, gälland… | 2315 |  |  | länkfält finns men exempelvärdet är relativt/internt:  |
| 1281 | Lund | arcgis | https://arcgisserver.lund.se/arcgis/rest/services/extern/Extern_Planin… | Gällande planer | 1142 | URL | EXTID, NAMN | URL = https://geoapi.lund.se/Plan/download?id=<akt> (nedladdning av planhandlingar). Datum… |
| 1284 | Höganäs | arcgis | https://maps.hoganas.se/arcgis/rest/services/DPL/Digitaliserade_detalj… | DPL/Digitaliserade_detaljplaner/Planområ… | 500 | DocumentLinks, DocumentLinksHtml |  |  |
| 1285 | Eslöv | arcgis | https://kartportal.eslov.se/arcgis/rest/services/kommun/gallande_detal… | kommun/gallande_detaljplaner/Gällande de… | 401 | lank_detaljplan | planbeteckning_lm |  |
| 1286 | Ystad | arcgis | https://kartportal.ystad.se/arcgis/rest/services/ALM/ALM_Planer_extern… | ALM/ALM_Planer_extern/Gällande detaljpla… | 426 | Planbeskrivning_pdf_länk, Plankarta_pdf_länk, Illustrationsplan_pdf_lank, Plankarta_ändring_1 |  |  |
| 1287 | Trelleborg | arcgis | https://geodata.trelleborg.se/arcgis/rest/services/Bygglov/Lagakraftvu… | Bygglov/Lagakraftvunna_planer/Planområde | 459 | DocumentLinks, DocumentLinksHtml |  |  |
| 1291 | Simrishamn | arcgis | https://services9.arcgis.com/NkmmUTvsR98rrIbx/arcgis/rest/services/Byg… | ByggaBo/Detaljplaner Lantmäteriet | 778 | URL |  |  |
| 1293 | Hässleholm | arcgis | https://geodata.hassleholm.se/arcgis/rest/services/planering/Planering… | planering/Planering_extern/Gällande deta… | 633 | plankartor | lmakt, plannr | länkfält finns men exempelvärdet är relativt/internt: 1 |
| 1315 | Hylte | arcgis | https://geosecma.hylte.se/arcgis/rest/services/Diverse/DetPl_OmrBest/M… | Diverse/DetPl_OmrBest/Planområden med pl… | 40 | Hyperlank, Ortlank, Plankartlank, Planbesklank | Plan_nr, Plannr_kort | länkfält finns men exempelvärdet är relativt/internt: \\hylte.net\dfs\Data\SBK\Samhällsbyg… |
| 1380 | Halmstad | wfs | https://karta.halmstad.se/geoserver/bmf/wfs?service=WFS&version=2.0.0&… | bmf:detaljplaner | 1162 | dokument (mall: https://karta.halmstad.se/files/detaljplaner/{dokument}.pdf, {dokument}.Planbeskrivning.pdf, geopackage/{dokument}.zip) | aktbeteckning, lmakt, plannummer, beskriv | Hajk 4.4, config /api/v2/config/ext. GeoServer WFS öppet (MultiPolygon). Dokumentlänk bygg… |
| 1384 | Kungsbacka | wfs | https://karta.kungsbacka.se/geoserver/wfs?service=WFS&version=2.0.0&re… | kba:fys_pla_dp_kba_lm_y | 1876 | karta/bestam/beskrivning (flaggor; mall https://karta.kungsbacka.se/linked_docs/dp/pdf/{plannamn}.Plankarta.pdf \| .Planbestämmelser.pdf \| .Planbeskrivning.pdf) | plannamn | Hajk 4.2 (config /publik/api/v2/config/publik). GeoServer WFS öppet (Polygon). Länk byggs … |
| 1401 | Härryda | arcgis | https://kartor.harryda.se/arcgis/rest/services/Harrydakartan/Harrydaka… | Harrydakartan/Harrydakartan_ByggaBoMiljo… | 500 | Plankarta, Sokvag_Plankarta | PlanID | länkfält finns men exempelvärdet är relativt/internt:  |
| 1402 | Partille | arcgis | https://geodata.partille.se/arcgis/rest/services/gallande_detaljplaner… | gallande_detaljplaner_publik/gallande_de… | 431 | plankarta | plannr | länkfält finns men exempelvärdet är relativt/internt:  |
| 1419 | Tjörn | arcgis | https://gis.tjorn.se/arcgis/rest/services/Fastighetsavd/planer20240318… | Fastighetsavd/planer20240318_extern_test… | 306 | plankarta_URL, planbeskr_URL |  | länkfält finns men exempelvärdet är relativt/internt:   |
| 1421 | Orust | arcgis | https://services2.arcgis.com/1Nvz85KbF7OLwYjb/arcgis/rest/services/Gal… | Gallande_detaljplaner/Gällande_detaljpla… | 413 | Links_1, Links_2, Links_3, Links_4 | Plan_Nr |  |
| 1427 | Sotenäs | arcgis | https://services7.arcgis.com/jFiNkvhOzEXq569w/arcgis/rest/services/Byg… | Bygga_Bo/Gällande detaljplaner | 452 | http_lank |  |  |
| 1435 | Tanum | arcgis | https://geodata.tanum.se/arcgis/rest/services/Bygga_och_bo/Detaljplane… | Bygga_och_bo/Detaljplaner_och_Lediga_tom… | 1 | Lank, Lank_plankarta | Diarienummer | länkfält finns men exempelvärdet är relativt/internt:  |
| 1439 | Färgelanda | arcgis | https://fargelanda-karta.geoassistans.nu/arcgis/rest/services/Plangrän… | Plangränser | 210 | Länk | PLANBET, EXTERNID, PLNAMN | ArcGIS Enterprise hos Geoassistans. 210/210 har Länk (PDF på www.fargelanda.se/media/). We… |
| 1441 | Lerum | arcgis | https://hittalerum.lerum.se/arcgis/rest/services/Gällande_planer_och_b… | Gällande detaljplan | 280 | Länk_intern_K (plankarta), Länk_intern_B (beskrivning), LANKADE_DOKUMENT | AKTNR_LMV, DP_NR, PLANNAMN | ArcGIS Enterprise 11.3. 280/280 har Länk_intern_K (https://hittalerum.lerum.se/PublikaDoku… |
| 1445 | Essunga | arcgis | https://geoportal.goliska.se/arcgis/rest/services/Essunga/Planer_Essun… | Gällande detaljplaner | 73 | Ext_lank | ARKIVNUMMER, Planens_namn | Göliska GIS ArcGIS Server 10.9.1. Ext_lank -> https://karta.goliska.se/Ess_Dplan/<nr>.pdf.… |
| 1452 | Tranemo | arcgis | https://gisportal.tranemo.se/arcgis/rest/services/Tranemokartan/Bygga_… | Tranemokartan/Bygga_och_bo/Gällande deta… | 283 | URL | Dnr |  |
| 1461 | Mellerud | arcgis | https://services-eu1.arcgis.com/0nc1EbIdg7uqEhpW/arcgis/rest/services/… | Planlager_-_Mellerud | 65 | Plankarta, Planbeskri, Utr1, Utr2 | Aktnummer, Namn | ArcGIS Online (EU). Två lager: Planlager_-_Mellerud (65) och Detaljplaner_-_Dals_Rostock/F… |
| 1463 | Mark | arcgis | https://kartor.mark.se/arcgis/rest/services/Samhallsplanering/Gallande… | Samhallsplanering/Gallande_planer/Gällan… | 462 | PDF |  |  |
| 1470 | Vara | arcgis | https://geoportal.vara.se/arcgis/rest/services/GEOSECMA/Karta/MapServe… | GEOSECMA/Karta/Gällande_detaljplaner | 424 | Plandokument |  |  |
| 1471 | Götene | arcgis | https://geoportal.gotene.se/arcgis/rest/services/Bygg/Bygglov_hemsida_… | Bygg/Bygglov_hemsida_NY/Detaljplaner | 244 | sde_gotene.GNG.py_lank.OBJECTID, sde_gotene.GNG.py_lank.OBJECTID_1, sde_gotene.GNG.py_lank.PLANBET, sde_gotene.GNG.py_lank.LINK |  | länkfält finns men exempelvärdet är relativt/internt: 63 |
| 1472 | Tibro | arcgis | https://enterprise.tibro.se/arcgis/rest/services/Detaljplan/MapServer/… | Detaljplanområden | 188 | Länk_2, Leverantör (gammal länk) | Detaljplan (plannr), Namn_1 | ArcGIS Enterprise 11.3 (publik REST). 188/188 har Länk_2 -> https://enterprise.tibro.se/po… |
| 1480 | Göteborg | wfs | https://geodata-external.sbk.goteborg.se/services/planer-v3/wfs?servic… | planer-v3:planer | 8037 | url | beteckning, text, beskrivning | Hajk (mapservice v1: /mapservice/config/layers). GeoServer WFS 2.0 öppet (json, csv, shape… |
| 1486 | Strömstad | arcgis | https://geodata.stromstad.se/arcgis/rest/services/Allmanna/Kommunspeci… | Allmanna/Kommunspecifika_lager/FDP Detal… | 2 | LÄNK_FÖR_NORRA_KUSTOMRÅDET | AKTUELL |  |
| 1490 | Borås | arcgis | https://kartportalen.boras.se/server/rest/services/Borås_bygger_Detalj… | Borås_bygger_Detaljplaner/Detaljplaner g… | 1166 | link, dokument_kartportalen | aktbet, altakt | länkfält finns men exempelvärdet är relativt/internt: Lankade_dokument/Planer/P745.pdf |
| 1491 | Ulricehamn | arcgis | https://gisportal.ulricehamn.se/arcgis/rest/services/Hosted/Gällande_d… | Hosted/Gällande_detaljplaner/Gällande de… | 976 | hyperlänk |  |  |
| 1494 | Lidköping | arcgis | http://geoportal.lidkoping.se/arcgis/rest/services/Hänsynskarta/MapSer… | Hänsynskarta/Område med gällande detaljp… | 1 | Länk | Aktuell | länkfält finns men exempelvärdet är relativt/internt:   |
| 1495 | Skara | arcgis | https://geoportal.goliska.se/arcgis/rest/services/Skara/Ext_Bygga_bo_m… | detaljplan_y | 289 | Ext_link | Namn, Beskrivning | Skarakartan är Origo; planlagret serveras från Göliska GIS ArcGIS Server. Ext_link -> http… |
| 1497 | Hjo | arcgis | https://gis.hjo.se/arcgis/rest/services/Plan/Detaljplaner/MapServer/1 | Plan/Detaljplaner/Detaljplan, laga kraft | 215 | DocumentLinks, DocumentLinksHtml |  |  |
| 1498 | Tidaholm | arcgis | https://geodata.tidaholm.se/arcgis/rest/services/Plan/Gällande_planer/… | Plan/Gällande_planer/Planområde | 99 | DocumentLinks, DocumentLinksHtml |  | länkfält finns men exempelvärdet är relativt/internt:  |
| 1499 | Falköping | wfs | https://karta.falkoping.se/geoserver/extern/ows?service=WFS&version=2.… | extern:lm_plan_yta_y_egnmod_gdp | 582 | ext_filnamn (prefix https://karta.falkoping.se/pdf_pk/ + .pdf; 134/582 ifyllda), ext_filnamn_pb (prefix https://karta.falkoping.se/pdf_pb/ + .pdf), url_plankarta, url_planbeskrivning | planbet, externid, plnamn | Origo (falk.json). Lagret är WMS i visaren men samma typename finns via WFS på extern/ows.… |
| 1761 | Hammarö | arcgis | https://gis.hammaro.se/server/rest/services/planer/Planmosaik_vektor/M… | planer/Planmosaik_vektor/Planområde | 174 | dp_syftedokumentation | dp_planid, dp_akt, dp_internakt, dp_ursprungsakt | länkfält finns men exempelvärdet är relativt/internt:  |
| 1765 | Årjäng | arcgis | https://gisportal.arjang.se/arcgis/rest/services/ArjangsKarttjanster/D… | ArjangsKarttjanster/Detaljplaner_Årjängs… | 190 | Lank | AKT_NR |  |
| 1780 | Karlstad | wfs | https://gi.karlstad.se/geoserver/ows?service=WFS&version=2.0.0&request… | webbkartan:webbkarta_gallande_planer | 995 | url, pdf_url | akt, webid | Karlstadskartan (Origo). WFS-lager webbkarta_gallande_planer har url -> gi.karlstad.se/pla… |
| 1784 | Arvika | arcgis | https://gis.arvika.se/arcgis/rest/services/Planer/DP_OB/MapServer/99 | Planer/DP_OB/Detaljplaner och områdesbes… | 429 | Detaljplan_pdf, Planbeskrivning_pdf, Plankarta_png | Planbeteckning |  |
| 1814 | Lekeberg | wfs | https://wms-extern.sydnarke.se/geoserver/klek_lmv_pbr_v1/ows?service=W… | klek_lmv_pbr_v1:plan_dp_yta | 109 | url_pdf | planbet, aktbet, externid | Hajk-karta via Sydnärkes byggförvaltning; GeoServer WFS, EPSG:3009. url_pdf -> dokumentark… |
| 1860 | Laxå | wfs | https://wms-extern.sydnarke.se/geoserver/klax_lmv_pbr_v1/ows?service=W… | klax_lmv_pbr_v1:plan_dp_yta | 153 | url_pdf | planbet, aktbet, externid | Samma struktur som Lekeberg (Sydnärke). EPSG:3009. |
| 1863 | Hällefors | arcgis | https://gis.sb-bergslagen.se/arcgis/rest/services/Fysiskplanering/Plan… | Planöversikt samtliga planer | 119 | Plan_pdf, Plan_text, Plan_pdf_2 | PlanID_BMB, PlanID_MG, PlanID_LMV | Gemensamt lager för Hällefors/Lindesberg/Ljusnarsberg/Nora, filtrera Kommunnamn='Hallefors… |
| 1864 | Ljusnarsberg | arcgis | https://gis.sb-bergslagen.se/arcgis/rest/services/Fysiskplanering/Plan… | Planöversikt samtliga planer | 112 | Plan_pdf, Plan_text, Plan_pdf_2 | PlanID_BMB, PlanID_MG, PlanID_LMV | Filtrera Kommunnamn='Ljusnarsberg'. |
| 1880 | Örebro | wfs | https://externkarta.orebro.se/api/v2/proxy/qgisserver/maps/Externkarta… | dp_planomradesytor_y | 3161 | plankarta, planbeskrivning | externid | Hajk-karta (Bygglovskartan) med QGIS Server via Hajk-proxy; WFS GetFeature (GeoJSON, WGS84… |
| 1881 | Kumla | arcgis | https://karta.kumla.se/arcgis/rest/services/ByggaBo_Hallsberg/ByggaBo_… | ByggaBo_Hallsberg/ByggaBo_Hallsberg/Plan… | 67 | DocumentLinks, DocumentLinksHtml |  | länkfält finns men exempelvärdet är relativt/internt:  |
| 1882 | Askersund | wfs | https://wms-extern.sydnarke.se/geoserver/kask_lmv_pbr_v1/ows?service=W… | kask_lmv_pbr_v1:plan_dp_yta | 237 | url_pdf | planbet, aktbet, externid | Samma struktur som Lekeberg (Sydnärke). EPSG:3009. |
| 1884 | Nora | arcgis | https://gis.sb-bergslagen.se/arcgis/rest/services/Fysiskplanering/Plan… | Planöversikt samtliga planer | 176 | Plan_pdf, Plan_text, Plan_pdf_2 | PlanID_BMB, PlanID_MG, PlanID_LMV | Filtrera Kommunnamn='Nora'. Även Fysiskplanering/Digital_dp_Nora (digitala planbestämmelse… |
| 1885 | Lindesberg | arcgis | https://gis.sb-bergslagen.se/arcgis/rest/services/Fysiskplanering/Plan… | Planöversikt samtliga planer | 312 | Plan_pdf, Plan_text, Plan_pdf_2 | PlanID_BMB, PlanID_MG, PlanID_LMV | Filtrera Kommunnamn='Lindesberg'. Även Fysiskplanering/Digital_dp_Lindesberg. |
| 1904 | Skinnskatteberg | download | https://karta.skinnskatteberg.se/data/detaljplaner.geojson | detaljplaner (GeoJSON) | 95 | PDF | planbet, externid | Origo-karta läser statisk GeoJSON (EPSG:3857) med MultiPolygon; PDF-fält relativt karta.sk… |
| 1960 | Kungsör | arcgis | https://geodata.kungsor.se/arcgis/rest/services/Planmosaik/MapServer/0 | Planmosaik/sde_kungsor.GNG.planytor | 186 | Hyperlink1, Hyperlink2, Hyperlink3, Hyperlink4 |  |  |
| 1962 | Norberg | wfs | https://karta.vdmb.se/geoserver/ows?service=WFS&version=2.0.0&request=… | db_gamla:dp_plangrans_y_n | 80 | plankarta, plandok1, plandok2, plandok3, plandok4 | plannr, plannr_lm | Länkfälten innehåller HTML-ankare (<a href="https://karta.vdmb.se/PDFService/Tittskap/Norb… |
| 1980 | Västerås | arcgis | https://gisportal.vasteras.se/server/rest/services/int/Analys_detaljpl… | int/Analys_detaljplaner/Detaljplaner_ana… | 48 | Lank |  |  |
| 1981 | Sala | arcgis | https://geodata.sala.se/arcgis/rest/services/Detaljplaner/Planområde/M… | Detaljplaner/Planområde/Gällande planer | 323 | URL | Plannr, LM_Plannr | länkfält finns men exempelvärdet är relativt/internt:  |
| 1982 | Fagersta | wfs | https://karta.vdmb.se/geoserver/ows?service=WFS&version=2.0.0&request=… | db_gamla:dp_plangrans_y_f | 218 | plankarta, plandok1, plandok2, plandok3, plandok4 | plannr, plannr_lm | Som Norberg; HTML-ankare i länkfält. lagakraft kan vara null för äldre planer. |
| 1983 | Köping | arcgis | https://geodata.koping.se/arcgis/rest/services/Bygga_bo_henriktest2609… | Bygga_bo_henriktest260904/Gällande detal… | 298 | url, link, linkcleartext |  |  |
| 1984 | Arboga | arcgis | https://geodata.arboga.se/arcgis/rest/services/DP/Detaljplaner_web/Fea… | DP/Detaljplaner_web/Detaljplaner | 277 | Länk | Beteckning |  |
| 2029 | Leksand | wfs | https://karta.leksand.se/geoserver/ows | adm-karta:utredningar_detaljplan | 28 |  |  | länkfält finns men exempelvärdet är relativt/internt:  |
| 2031 | Rättvik | wms | https://ows.rattvik.se/gis/fastighetsuppgifter?SERVICE=WMS&VERSION=1.1… | gallande_planer |  | linktxt | originalid | Ingen WFS (FeatureTypeList tom) men WMS GetFeatureInfo returnerar GeoJSON med polygon och … |
| 2034 | Orsa | wfs | https://karta.orsa.se/geoserver/ows?service=WFS&version=2.0.0&request=… | visa_dp_orsa | 138 | dp | externid, dp | Länk byggs som https://karta.orsa.se/img/PDF/planer/{dp}.pdf (verifierad 200). Inga datumf… |
| 2039 | Älvdalen | wfs | https://karta.alvdalen.se/geoserver/ows?service=WFS&version=2.0.0&requ… | planer_alv | 246 |  | planbet, externid | Inget URL-fält men Origo-konfig länkar /img/pdf/detaljplaner/{planbet}.PDF (https://karta.… |
| 2061 | Smedjebacken | arcgis | https://geodata.smedjebacken.se/arcgis/rest/services/Plan/Detaljplaner… | Plan/Detaljplaner_lagakraft/Eget temalag… | 176 | DocumentLinks, DocumentLinksHtml |  | länkfält finns men exempelvärdet är relativt/internt: \\tsclient\I\miljö\Plan\DETALJPLANER… |
| 2062 | Mora | wfs | https://karta.morakommun.se/geoserver/ows?service=WFS&version=2.0.0&re… | visa_dp_mora | 364 | dp | externid, dp | Länk byggs som https://karta.morakommun.se/img/PDF/planer/{dp}.pdf (verifierad 200). Inga … |
| 2081 | Borlänge | arcgis | https://geodata.borlange.se/server/rest/services/Borlangekartan/Borlan… | Borlangekartan/Borlangekartan/Gällande d… | 476 | URL, URL_out | PLANNR, PLANNR_1 |  |
| 2082 | Säter | arcgis | https://services-eu1.arcgis.com/Edg0lenBBoWlakRf/arcgis/rest/services/… | Detaljplaner_Ytor/Detaljplaner_Ytor | 163 | LANKADP, LANKKARTA, LANKTEXT | ADPBETECKN | länkfält finns men exempelvärdet är relativt/internt:   |
| 2084 | Avesta | wfs | https://karta.vdmb.se/geoserver/ows?service=WFS&version=2.0.0&request=… | db_gamla:dp_plangrans_y_a | 356 | plankarta, plandok1, plandok2, plandok3, plandok4 | plannr, plannr_lm | Som Norberg; HTML-ankare i länkfält (karta.vdmb.se/PDFService/Tittskap/Avesta/Plan/...). |
| 2101 | Ockelbo | arcgis | https://gis.sandviken.se/server/rest/services/Planarkiv/MapServer/2 | Detaljplaner | 113 | pdf_plats | akt | Gemensamt planarkiv för Sandviken/Hofors/Ockelbo (totalt 988); filtrera kommun='OCKELBO'. … |
| 2104 | Hofors | arcgis | https://gis.sandviken.se/server/rest/services/Planarkiv/MapServer/2 | Detaljplaner | 223 | pdf_plats | akt | Filtrera kommun='HOFORS'. Exempel pdf_plats https://karta.sandviken.se/geodata/planarkiv/V… |
| 2121 | Ovanåker | arcgis | https://maps.ovanaker.se/arcgis/rest/services/databaser/MapServer/113 | databaser/Detaljplaneöversikt | 176 | URL |  |  |
| 2132 | Nordanstig | wfs | https://karta.nordanstig.se/geoserver/ows | RIGES:DetaljplanGallande_minusNGP_yta | 590 | PLANKARTA | AKTBET, AKTBET_LOK |  |
| 2181 | Sandviken | arcgis | https://gis.sandviken.se/server/rest/services/Planarkiv/FeatureServer/… | Planarkiv/Detaljplaner | 988 | pdf_plats | akt |  |
| 2182 | Söderhamn | arcgis | https://gisportal.soderhamn.se/arcgis/rest/services/Detaljplan/Detaljp… | Detaljplan/Detaljplanemosaik/Planområde | 27 | DocumentLinks, DocumentLinksHtml |  |  |
| 2183 | Bollnäs | arcgis | https://gis.bollnas.se/arcgis/rest/services/Planer/Detaljplaner_extern… | Planer/Detaljplaner_extern/Detaljplan_ko… | 402 | karta_link, related_links |  | länkfält finns men exempelvärdet är relativt/internt: \\bkfs-05\Gemensam\Gemensam SBK\IT\G… |
| 2184 | Hudiksvall | arcgis | https://kartor.hudiksvall.se/arcgis/rest/services/Avd_PlanBygg/Avd_Pla… | Avd_PlanBygg/Avd_PlanBygg_Planer_Ext/Gäl… | 507 |  |  | länkfält finns men exempelvärdet är relativt/internt:  |
| 2260 | Ånge | wfs | https://karta.ange.se/geoserver/ows | RIGES:DetaljplanGallande_minusNGP_yta | 590 | PLANKARTA | AKTBET, AKTBET_LOK |  |
| 2262 | Timrå | arcgis | https://kartor.timra.se/arcgis/rest/services/Gällande_detaljplaner/Fea… | Gällande_detaljplaner/Planområden | 196 | url | AKTBET, AKTBET_LOK | länkfält finns men exempelvärdet är relativt/internt:   |
| 2281 | Sundsvall | wfs | https://karta.sundsvall.se/geoserver/ows | RIGES:DetaljplanGallande_minusNGP_yta | 590 | PLANKARTA | AKTBET, AKTBET_LOK |  |
| 2309 | Krokom | download | https://kartor.krokom.se/detaljplaner/layers/Detaljplaner_2.js | Detaljplaner_2 | 277 | Länk_1, Länk_2, Länk_3, Länk_4, Länk_5 | BESKRIV, PLANNR | qgis2web-sida; GeoJSON (CRS84) inbäddad i JS-fil 'var json_Detaljplaner_2 = {...}'. Länkfä… |
| 2321 | Åre | download | https://kartor.are.se/detaljplaner/layers/Detaljplaner_2.js | Detaljplaner_2 | 507 | LINK | PLANBET | qgis2web-sida; GeoJSON (CRS84) inbäddad i JS. Fält: fid, LINK (ren URL till https://kartor… |
| 2482 | Skellefteå | arcgis | https://gis.skelleftea.se/arcgis/rest/services/Fysisk_planering/Planmo… | Fysisk_planering/Planmosaik/Planområde | 186 | dp_syftedokumentation | dp_planid, dp_akt, dp_internakt, dp_ursprungsakt | länkfält finns men exempelvärdet är relativt/internt:  |
| 2505 | Arvidsjaur | arcgis | https://externgis.arvidsjaur.se/server/rest/services/Kommuninformation… | Planområde (lager 5) | 150 | DocumentLinks, DocumentLinksHtml | DocumentName, Name, RegistrationNumber | ArcGIS Enterprise (externgis.arvidsjaur.se, REST-rot /server/rest/services). Web AppBuilde… |
| 2510 | Jokkmokk | arcgis | https://geoportal.jokkmokk.se/arcgis/rest/services/Detaljplaner/Detalj… | Detaljplaner/Detaljplaner_Laga_kraft_201… | 3 | DocumentLinks, DocumentLinksHtml |  | länkfält finns men exempelvärdet är relativt/internt:  |
| 2514 | Kalix | arcgis | https://karta.kalix.se/arcgis/rest/services/02_ByggaochBo/Gallande_det… | 02_ByggaochBo/Gallande_detaljplaner/Plan… | 120 | DocumentLinks, DocumentLinksHtml |  |  |
| 2521 | Pajala | arcgis | https://karta.pajala.se/arcgis/rest/services/Portal/DetaljplanerInvent… | Portal/DetaljplanerInventering/Detaljpla… | 138 | mapplank |  | länkfält finns men exempelvärdet är relativt/internt: file:///K:/Samhallsplanering/Detaljp… |
| 2523 | Gällivare | arcgis | https://kartor.gallivare.se/arcgisportal/rest/services/Detaljplaner/De… | Detaljplaner | 421 | URL_Plankarta, URL_Planbeskrivning | planbet_1 | ArcGIS Enterprise på kartor.gallivare.se (REST-rot /arcgisportal/rest/services, ej /arcgis… |
| 2580 | Luleå | arcgis | https://kartportal.lulea.se/server/rest/services/samhalle_och_gator/Ma… | samhalle_och_gator/Detaljplan | 798 |  | LM_AKT_NR | länkfält finns men exempelvärdet är relativt/internt:  |
| 2581 | Piteå | arcgis | https://gisportal.pitea.se/arcgis/rest/services/PK_PUBLIK/PK_Detaljpla… | PK_PUBLIK/PK_Detaljplaner_digitala_galla… | 21 | DocumentLinks, DocumentLinksHtml |  | länkfält finns men exempelvärdet är relativt/internt: \\it.pitea.se\dfsroot\KOMMUNGEMENSAM… |
| 2582 | Boden | arcgis | https://gisportal.boden.se/server/rest/services/AD_DB_GIS_MBKMOP/BK_WE… | AD_DB_GIS_MBKMOP/BK_WEBBGIS_BODEN_BYGG_B… | 603 | DocumentLinksWebHtml |  |  |
| 2584 | Kiruna | arcgis | https://geoportal.kiruna.se/arcgis/rest/services/Externwebb/Externwebb… | Externwebb/Externwebb_Stadsomvandling/De… | 316 | sde_gsd.GNG.TABLE_PLAN_URL.URL_KARTA1, sde_gsd.GNG.TABLE_PLAN_URL.URL_KARTA2, sde_gsd.GNG.TABLE_PLAN_URL.URL_BESKR, sde_gsd.GNG.TABLE_PLAN_URL.WEBBSIDA |  | länkfält finns men exempelvärdet är relativt/internt:  |

## B. Öppet lager utan dokumentlänk (35)

| Kod | Kommun | Typ | Endpoint | Lager | Antal | Länkfält | Akt-fält | Anteckning |
|---|---|---|---|---|---|---|---|---|
| 0117 | Österåker | arcgis | https://gisportal.osteraker.se/arcgis/rest/services/Österåker/Detaljpl… | Österåker/Detaljplaner/Detaljplaner | 390 |  |  |  |
| 0162 | Danderyd | arcgis | https://kartportalen.danderyd.se/arcgis/rest/services/S%C3%B6k_plan/Ma… | Endast plan (Sök_plan/MapServer/30) | 535 |  | PLANNR, LMAKT | Experience Builder-app 'Gällande detaljplaner Danderyd' (portal search). Lager 30 'Endast … |
| 0331 | Heby | arcgis | https://kartor.heby.se/arcgis/rest/services/Kommunkarta/Detaljplaner/M… | Kommunkarta/Detaljplaner/Planer med plan… | 78 |  |  |  |
| 0561 | Åtvidaberg | arcgis | https://karta.atvidaberg.se/arcgis/rest/services/Hosted/Kvartersindeln… | Hosted/Kvartersindelning_Norrby_etapp_1/… | 15 |  |  |  |
| 0580 | Linköping | arcgis | https://kartor.linkoping.se/arcgis/rest/services/detaljplanekartan/det… | detaljplanekartan/detaljplanekartan_p/Pl… | 3371 |  | IDNR, PLANNR |  |
| 0767 | Markaryd | wfs | https://karta.markaryd.se/api/v2/proxy/geoserver/geoserver/wfs?service… | ws-Detaljplan:Detaljplaner (även Stadspl… | 132 |  | BESKRIV, PLANNR, PLANNAMN | Hajk v4 med GeoServer via proxy. Inget URL-fält, men dokumentlänk byggs av PLANNR: https:/… |
| 0781 | Ljungby | arcgis | https://services3.arcgis.com/qGjcvnBJeMdslvY0/arcgis/rest/services/Pla… | Planomrade_ljungby7131/Planomrade_7_131 | 1 |  | PLANID |  |
| 0882 | Oskarshamn | arcgis | https://services2.arcgis.com/WpTpIYmf7RFMR4yi/arcgis/rest/services/Lyc… | Lyckeberg_WFL1/Plangrans | 2 |  |  |  |
| 1081 | Ronneby | wfs | https://karta.ronneby.se/geoserver/ows | TFK:Detaljplaner | 384 |  |  |  |
| 1214 | Svalöv | arcgis | https://gisportal.perstorp.se/arcgis/rest/services/Svalöv/Gällande_det… | Planytor Svalöv | 192 |  | PLANBET, EXTERNID, LokalBet, PLNAMN | Fälten Lank1/Lank2 innehåller bara PDF-filnamn (t.ex. '1197 Kågeröd 15_1 mfl (centrum).pdf… |
| 1256 | Östra Göinge | arcgis | https://kartportal.unikom.se/arcgis/rest/services/og_planering/Planeri… | Detaljplaner | 399 |  | dp_aktnummer, dp_plannummer, dp_plannamn | Unikom (Osby/Östra Göinge m.fl.). Fält ex_lank_planbeskrivning/ex_lank_plankarta innehålle… |
| 1257 | Örkelljunga | arcgis | https://gts.klippan.se/arcgis/rest/services/Orkelljunga/Örkelljunga_fä… | Planområde | 160 |  | RegistrationNumber, DocumentName, Name | Planområde-lager med Geosecma-fält (Name, Regulations, DocumentName=akt). DocumentLinks to… |
| 1265 | Sjöbo | arcgis | https://gis.sjobo.se/arcgis/rest/services/Extern/Byggabomiljo/MapServe… | Extern/Byggabomiljo/Detaljplaner | 229 |  |  |  |
| 1273 | Osby | arcgis | https://kartportal.unikom.se/arcgis/rest/services/osby_planering_detal… | Detaljplan | 369 |  | dp_aktnummer, plannr, plannamn | ex_lank_planbeskrivning/ex_lank_plankarta = bara filnamn (.tif/.ecw), ingen bas-URL. Lager… |
| 1283 | Helsingborg | arcgis | https://kartportal.helsingborg.se/server1/rest/services/tema_samlingst… | Gränser för gällande detaljplaner | 1733 |  | planbet, externid, plnamn | Inget URL-fält; webbkartans popup bygger dokumentlänk som https://apps.icatserver.com/hbg/… |
| 1381 | Laholm | arcgis | https://kartor.laholm.se/arcgis/rest/services/gis/Detaljplan_pro/Featu… | gis/Detaljplan_pro/Gällande detaljplaner | 511 |  |  |  |
| 1383 | Varberg | wfs | https://wms.varberg.se/geoserver/ext_lm_v1/wfs?service=WFS&version=2.0… | ext_lm_v1:detaljplan_gallande_multi | 921 |  | beteckning, namn | Hajk 4.4 (config /api/v2/config/map_1). WFS öppet; fält beteckning (1383-P93/24), namn, de… |
| 1442 | Vårgårda | arcgis | https://gisportal.hervar.se/arcgis/rest/services/Samhällsplanering/Det… | Planområde | 129 | DocumentLinks/DocumentLinksHtml (finns men 0 ifyllda) | Name, Description | Gemensam ArcGIS Enterprise gisportal.hervar.se. Geosecma-planmodell med Planbestämmelser/E… |
| 1443 | Bollebygd | arcgis | https://services5.arcgis.com/nE6khkTBR5RPwbOu/arcgis/rest/services/Gäl… | Gällande detaljplaner | 118 | Planavgift_Lank_Dok (29/118 ifyllda, avser planavgift-dokument) | AktBeteckning, PlanNamn, Plan_id | ArcGIS Online hosted feature layer (EPSG:3008). PlanTyp (BP/DP..). Ingen generell planhand… |
| 1466 | Herrljunga | arcgis | https://gisportal.hervar.se/arcgis/rest/services/Samhällsplanering/Det… | Planområde | 131 | DocumentLinks (5/131 ifyllda, interna UNC-sökvägar) | Name, Description, RegistrationNumber | Geosecma-planmodell; DocumentLinks innehåller bara filserversökvägar (\\HV016\...) för 5 o… |
| 1484 | Lysekil | arcgis | https://services6.arcgis.com/wEpZ0jCGXtf4JWgt/arcgis/rest/services/Öve… | Överliggande_skikt/Preliminära havsplano… | 3 |  |  |  |
| 1762 | Munkfors | arcgis | https://services3.arcgis.com/DlbZcscGstAa5ye2/arcgis/rest/services/Det… | Detaljplaner_i_Munkfors_kommun/Detaljpla… | 77 |  |  |  |
| 1781 | Kristinehamn | arcgis | https://portal.kristinehamn.se/arcgis/rest/services/Portal/Plankarta/M… | Plan | 535 |  | planbet, externid, Plannummer | Polygonlager (plantyp, plnamn, planfk) men inget dokumentlänkfält. Webbapp 'Plankartan'. |
| 1861 | Hallsberg | arcgis | https://karta.kumla.se/arcgis/rest/services/Plan/Detaljplaner_Hallsber… | Detaljplaner | 411 |  | planbet | Polygonlager med planbet, plantyp, plnamn, bdat, ldat; inget länkfält. ByggaBo_Hallsberg/M… |
| 1907 | Surahammar | arcgis | https://gis.surahammar.se/arcgis/rest/services/Hosted/Detaljplanöversi… | Hosted/Detaljplanöversikt/dp_ytor | 125 |  |  |  |
| 2080 | Falun | arcgis | https://gis.falun.se/arcgis/rest/services/Falukartan/Bygga_bo_och_milj… | Falukartan/Bygga_bo_och_miljo/Detaljplan… | 819 |  | LMAKT, ALTAKT, PLANNR |  |
| 2083 | Hedemora | arcgis | https://geodata.hedemora.se/arcgis/rest/services/Topografi_10_Reg/MapS… | Topografi_10_Reg/Identitetspunkt för pla… | 267 |  |  |  |
| 2180 | Gävle | arcgis | https://gis.gavle.se/server/rest/services/pbf_planering/Planmosaik_gav… | pbf_planering/Planmosaik_gavle_image/Foo… | 2171 |  |  |  |
| 2280 | Härnösand | wfs | https://karta.sundsvall.se/geoserver/wfs?service=WFS&version=2.0.0&req… | RIGES:DetaljplanGallande_yta | 382 | PLANKARTA, PLANHANDL | AKTBET | karta.harnosand.se pekar på Sundsvalls Origo-server (samma IP, config index.json identisk … |
| 2284 | Örnsköldsvik | wfs | https://karta-ext.ornskoldsvik.se/geoserver/Extern/wfs?service=WFS&ver… | Extern:dp_ov_mosaik_plan_y_ext | 770 |  | dp_akt | Origo (config https://karta-ext.ornskoldsvik.se/Detaljplanekarta/index.json). GeoServer-WF… |
| 2326 | Berg | arcgis | https://services8.arcgis.com/XsJFX8TmXS8hVFq1/arcgis/rest/services/pla… | plangräns/plangräns | 1 |  | PLANID, Akt, Planid_1, InternAkt |  |
| 2380 | Östersund | arcgis | https://services-eu1.arcgis.com/UTjlzlFHM5lcOieP/arcgis/rest/services/… | Markanvändningskarta_BACKUP_karta2/Plang… | 2 |  |  |  |
| 2480 | Umeå | api | https://opendata.umea.se/api/explore/v2.1/catalog/datasets/gallande-de… | gallande-detaljplaner | 2007 |  | aktbet | Opendatasoft Explore v2.1, fält: aktbet, popularnam, datum, kategori, geo_shape (WGS84). I… |
| 2513 | Överkalix | arcgis | https://kartor.overkalix.se/arcgis/rest/services/Portal/Kommunkartan/M… | Portal/Kommunkartan/Detaljplan: gällande | 93 |  |  |  |
| 2518 | Övertorneå | arcgis | https://services3.arcgis.com/MmwmEBejHS52xPUD/arcgis/rest/services/Det… | Detaljplaner | 125 |  | externid | ArcGIS Online (org MmwmEBejHS52xPUD, ägare Mattias.gomez). Experience Builder 'Vad gäller … |

## D. Kartvisare finns, inget maskinläsbart planlager (75)

| Kod | Kommun | Typ | Endpoint | Lager | Antal | Länkfält | Akt-fält | Anteckning |
|---|---|---|---|---|---|---|---|---|
| 0114 | Upplands Väsby | geosecma | https://vasbykartan.upplandsvasby.se/spatialmap? |  |  |  |  | Sokigo SpatialMap (Väsbykartan). /wms kräver servicename; inget publikt servicename hittad… |
| 0115 | Vallentuna | geosecma | https://kommunkarta.vallentuna.se/spatialmap |  |  |  |  | Sokigo SpatialMap. /wms kräver servicename; inget publikt hittades. Planhandlingar som PDF… |
| 0123 | Järfälla | geosecma | https://jarfallakartan.jarfalla.se/spatialmap? |  |  |  |  | Sokigo SpatialMap (Järfällakartan). /wms kräver servicename; inget publikt hittades. |
| 0125 | Ekerö | geosecma | https://karta.ekero.se/spatialmap? |  |  |  |  | Sokigo SpatialMap. /wms kräver servicename; inget publikt hittades. |
| 0127 | Botkyrka | wms | https://karta.botkyrka.se/wms?servicename=wms&request=GetCapabilities&… | theme-detaljplaner / planmosaik_3 |  |  |  | SpatialMap WMS (servicename=wms) har lager 'Detaljplaner' och 'Planytor' men queryable=0 (… |
| 0128 | Salem | wms | https://karta.salem.se/wms?servicename=publik_webbkarta&request=GetCap… | dp_gallande (selectorgroup) |  |  |  | SpatialMap WMS (servicename=publik_webbkarta) nåbar men lager queryable=0; ingen WFS. Plan… |
| 0138 | Tyresö | wms | https://karta.tyreso.se/wms?servicename=publik_webbkarta&request=GetCa… |  |  |  |  | SpatialMap WMS (servicename=publik_webbkarta) nåbar men lager queryable=0; ingen WFS. |
| 0140 | Nykvarn | geosecma | https://karta.nykvarn.se/spatialmap |  |  |  |  | Sokigo SpatialMap. /wms kräver servicename; inget publikt hittades. |
| 0160 | Täby | geosecma | https://karta.taby.se/spatialmap |  |  |  |  | Sokigo SpatialMap. /wms kräver servicename; inget publikt hittades. |
| 0180 | Stockholm | egen (Stockholms stad) | https://kartor.stockholm/ |  |  |  |  | kartor.stockholm är en JS-app utan hittat öppet planlager. openstreetgs.stockholm.se/geose… |
| 0184 | Solna |  |  |  |  |  |  | Bara 'Detaljplan pågående' publikt i ArcGIS Online, inget gällande-lager |
| 0186 | Lidingö | wms | https://karta.lidingo.se/wms?servicename=wms_detaljplaner_oppendata&se… | theme-dp_planoversikt / dp_plan_y |  |  |  | Öppen WMS från dataportal.se-posten, men lagren är queryable=0 (ingen GetFeatureInfo) och … |
| 0187 | Vaxholm | geosecma | https://karta.vaxholm.se/spatialmap |  |  |  |  | Sokigo SpatialMap. /wms kräver servicename; inget publikt hittades. |
| 0188 | Norrtälje | api | https://karta.norrtalje.se/api/map |  |  |  |  | myCarta WebMap (Aveki). /api/map listar kartor (bl.a. 'Norrtälje kommuns webbkarta' 4169af… |
| 0191 | Sigtuna |  |  |  |  |  |  |  |
| 0192 | Nynäshamn | api | https://webbkarta.nynashamn.se/myCartaServer/maplist |  |  |  |  | myCarta WebMap. /myCartaServer/maplist ger kartor ('Webbkarta' MapFile=webmap). Lager-/fea… |
| 0305 | Håbo | geosecma | https://karta.habo.se/spatialmap |  |  |  |  | Håbokartan = Sokigo SpatialMap (kommunen har guide 'Hitta detaljplanen i Håbokartan'). /wm… |
| 0319 | Älvkarleby |  |  |  |  |  |  |  |
| 0360 | Tierp | geosecma | https://tierpskartan.tierp.se/spatialmap? |  |  |  |  | Tierpskartan = Sokigo SpatialMap. /wms kräver servicename; inget publikt hittades. Planhan… |
| 0382 | Östhammar | geosecma | https://karta.osthammar.se/spatialmap? |  |  |  |  | Sokigo SpatialMap. /wms kräver servicename; inget publikt hittades. |
| 0461 | Gnesta | geosecma | https://karta.gnesta.se/spatialmap |  |  |  |  | Sokigo SpatialMap. /wms kräver servicename; inget publikt hittades. |
| 0480 | Nyköping | geosecma | https://kartor.nykoping.se/spatialmap |  |  |  |  | Sokigo SpatialMap. /wms kräver servicename; inget publikt hittades. |
| 0483 | Katrineholm | api | https://geodata.katrineholm.se/api/3/action/package_search?q=detaljpla… |  |  |  |  | SpatialMap-visare; CKAN-portal geodata.katrineholm.se har bara 2 dataset (exploateringspro… |
| 0488 | Trosa | icebound SMART (AddSpatial) | https://addspatial.icebound.com/SMART/?profile=Trosa_op#map=trosa_pl%3… | trosa_pl:trosa_pl |  |  |  | Kommunens sida 'Gällande detaljplaner' länkar till Icebound SMART-visare med lager trosa_p… |
| 0581 | Norrköping | geosecma | https://kartor.norrkoping.se/spatialmap |  |  |  |  | Norrköpingskartan (NoKa) = Sokigo SpatialMap. /wms kräver servicename; inget publikt hitta… |
| 0604 | Aneby | metria (Geovis) | https://geovis-aneby.metria.se/ |  |  |  |  | Anebykartan (Metria Geovis) har lager 'Gällande detaljplaner'. Bakomliggande GeoServer /me… |
| 0682 | Nässjö | wms | https://karta.nassjo.se/wms?servicename=csm_standard_profile&service=W… | theme-detaljplaner_y |  |  |  | Spatial Suite. WMS (MapServer) finns med lager theme-detaljplaner_y men GetFeatureInfo ger… |
| 0684 | Sävsjö | wms | https://karta.savsjo.se/wms?servicename=csm_standard_profile&service=W… | theme-detaljplaner |  |  |  | Spatial Suite; WMS-lager theme-detaljplaner ej queryable (LayerNotQueryable), ingen WFS. K… |
| 0685 | Vetlanda | wms | https://karta.vetlanda.se/wms?servicename=csm_standard_profile&service… | theme-detaljplaner_l_filter_status_lagak… |  |  |  | Spatial Suite; WMS-lager ej queryable, ingen WFS. |
| 0686 | Eksjö | wms | https://karta.eksjo.se/wms?servicename=csm_standard_profile&service=WM… | theme-detaljplaner_oversikt |  |  |  | Spatial Suite; WMS-lager ej queryable, ingen WFS. Klick i visaren öppnar plankarta/planbes… |
| 0860 | Hultsfred | arcgis | https://gis-online.hultsfred.se/arcgis/rest/services/Överskridande_båd… | Planyta Hultsfred |  |  |  | Lager finns (Planyta Hultsfred, id 43) men query ger 'Requested operation is not supported… |
| 0862 | Emmaboda | arcgis (Portal) | https://kartor.emmaboda.se/portal/apps/webappviewer/index.html?id=7646… |  |  |  |  | Webbkarta 'Antagna planer' finns; dess webmap har lagret 'Planer' som inbäddad featureColl… |
| 0884 | Vimmerby | arcgis | https://gis-online.hultsfred.se/arcgis/rest/services/Överskridande_båd… | Planyta Vimmerby |  |  |  | Samma tjänst som Hultsfred; query ej tillåten. Planarkiv som PDF-lista per år (laga kraft … |
| 1278 | Båstad | wms | https://karta.bastad.se/wms?servicename=csm_standard_profile&service=W… | bastadkartan/kommunal_verksamhetsdata/pl… |  |  |  | Spatial Suite; WMS-lager för detaljplaner finns men GetFeatureInfo avvisas (LayerNotDefine… |
| 1282 | Landskrona | wms | https://karta.landskrona.se/wms?servicename=landskronakartan&service=W… |  |  |  |  | Landskronakartan (Spatial Suite) visar gällande detaljplaner enligt kommunsidan, men inga … |
| 1290 | Kristianstad | wfs | https://kartor.kristianstad.se/qgisserver-shared/ows/planer?SERVICE=WF… | planomrade_lk |  |  |  | Origo-konfig (index.json) visar WMS/WFS-källa 'planer' (QGIS Server) med lager planomrade_… |
| 1292 | Ängelholm | mapguide (CadQ GS Viewer) | https://karta.engelholm.se/Detaljplanekarta |  |  |  |  | Detaljplanekarta i MapGuide (Autodesk/CadQ). mapagent WMS/WFS GetCapabilities svarar men e… |
| 1382 | Falkenberg | cartesia-smart (Sokigo AddSpatial) | https://atlas.falkenberg.se/smart/?profile=Publik |  |  |  |  | Kommunens karta (karta.falkenberg.se) är en iframe till Cartesia/Sokigo SMART (atlas.falke… |
| 1407 | Öckerö | wms | https://karta.ockero.se/wms?servicename=csm_standard_profile&service=W… | theme-detaljplaner (Gällande planer) |  |  |  | SpatialSuite (cbKort). WMS GetCapabilities nås med servicename=csm_standard_profile; lagre… |
| 1415 | Stenungsund | spatialsuite + arcgis enterprise | https://kartan.stenungsund.se/spatialmap? |  |  |  |  | Kartportalen är SpatialSuite (profil extern) med detaljplaner som lager enligt kommunsidan… |
| 1430 | Munkedal |  |  |  |  |  |  | Bara pågående planer i ArcGIS Online |
| 1440 | Ale |  |  |  |  |  |  |  |
| 1446 | Karlsborg | wms | https://karta.karlsborg.se/myCartaServer/detaljplaner.wms?service=WMS&… | aa (Planöversikt) |  |  |  | myCarta WebMap. Kartan 'detaljplaner' finns som WMS (myCartaServer/<karta>.wms); GetFeatur… |
| 1447 | Gullspång | wms | https://karta.mariestad.se/myCartaWebMapAdmin/mycartaserver/antagna_de… | e0b5814a (Detaljplaner Gullspång) |  |  |  | Gemensam myCarta hos Mariestad (adminapi /api/Map listar kartor). Endast WMS; GetFeatureIn… |
| 1462 | Lilla Edet | wms | https://kommunkarta.lillaedet.se/mycartaserver/Kommunkartan.wms?servic… | 78457729 (Detaljplaner och övriga planer… |  |  |  | myCarta WebMap med adminapi. Endast WMS; GetFeatureInfo tomt i test. Ingen WFS/REST. |
| 1465 | Svenljunga | arcgis | https://kartor.svenljunga.se/arcgis/rest/services/Svenljungakartan/Kom… |  |  |  |  | Svenljungakartan (AGOL-app) använder ArcGIS Server kartor.svenljunga.se (Baskarta + Kommun… |
| 1473 | Töreboda | wms | https://karta.mariestad.se/myCartaWebMapAdmin/mycartaserver/antagna_de… | 1917937c (Detaljplaner) |  |  |  | Gemensam myCarta hos Mariestad. Endast WMS; GetFeatureInfo tomt i test. Ingen WFS/REST. |
| 1481 | Mölndal | wms | https://karta.molndal.se/wms?servicename=extern&service=WMS&request=Ge… | theme_detaljplaner_kombo (Gällande detal… |  |  |  | SpatialSuite; WMS med servicename=extern, lager theme_detaljplaner_kombo_sbf_detaljplan_i0… |
| 1482 | Kungälv | wms | https://kartor.kungalv.se/wms?servicename=kungalv&service=WMS&request=… | theme-planoversikt (Gällande detaljplane… |  |  |  | SpatialSuite; WMS servicename=kungalv har theme-planoversikt, theme-dp_omradesindelning_y,… |
| 1485 | Uddevalla |  |  |  |  |  |  |  |
| 1487 | Vänersborg | wms | https://karta.vanersborg.se/myCartaServer/V%C3%A4nersborgWebbkarta.wms… | 0532b57a (Gällande Planer) |  |  |  | myCarta WebMap (maplisthandler.ashx listar kartor). Endast WMS; GetFeatureInfo tomt i test… |
| 1488 | Trollhättan | wms | https://kartportalen.trollhattan.se/wms?servicename=csm_standard_profi… | theme-pdp_planover_vw (Planområden) |  |  |  | Planarkivet i SpatialSuite; WMS servicename=csm_standard_profile har theme-pdp_planover_vw… |
| 1489 | Alingsås |  |  |  |  |  |  | ArcGIS Online: 'Pågående detaljplaner' (47, Link) och 'D - Område med detaljplan' (ej veri… |
| 1493 | Mariestad | wms | https://karta.mariestad.se/myCartaWebMapAdmin/mycartaserver/antagna_de… | 122162ee (Antagna detaljplaner) |  |  |  | myCarta WebMap (admin-API /api/Map). Endast WMS; GetFeatureInfo tomt i test. Ingen WFS/RES… |
| 1496 | Skövde | wms | https://karta.skovde.se/myCartaServer/Plan_och_bygglovskartan.wms?serv… | f3a1334b (Detaljplaner, 'innehåller länk… |  |  |  | myCarta (äldre emap-klient). Lagerbeskrivning säger att lagret har länk till planakten, me… |
| 1715 | Kil | geosecma | https://karta.kil.se/spatialmap? |  |  |  |  | Geosecma SpatialMap-kartportal; ingen ArcGIS REST under /arcgis eller /server på karta.kil… |
| 1730 | Eda | wms | https://webmap.eda.se/ |  |  |  |  | myCarta WebMap (Aveki). mycartaserver listar WMS-kartor men inget detaljplanelager; admin-… |
| 1737 | Torsby | wms | https://maps.torsby.se/mycartaserver/Webkarta.wms?service=wms&request=… | da43f5e7 (Detaljplaner) |  |  |  | myCarta WMS med lager 'Detaljplaner' (da43f5e7) och 'Pågående planering' (bb8cc403); GetFe… |
| 1763 | Forshaga | wms | https://karta.forshaga.se/ |  |  |  |  | myCarta WebMap; mycartaserver har 16 WMS-kartor, inget detaljplanelager. |
| 1764 | Grums | wms | https://karta.grums.se/ |  |  |  |  | karta.grums.se är myCarta WebMap (Grumskartan_extern.wms m.fl.) utan planlager. Äldre ArcG… |
| 1785 | Säffle | wms | https://webmap.saffle.se/ |  |  |  |  | myCarta WebMap; Extern_HuvudKarta_WebMap.wms saknar planlager. |
| 1883 | Karlskoga | wms | https://karlskogakartan.karlskoga.se/WebMap/myCartaServer/Overlay_ext.… | 14737e0c (Detaljplaner) |  |  |  | myCarta WMS-lager 'Detaljplaner' i Overlay_ext; GetFeatureInfo returnerade tom FeatureColl… |
| 1961 | Hallstahammar |  |  |  |  |  |  | Bara WMS (Detaljplan planpresentation) i ArcGIS Online |
| 2026 | Gagnef | geosecma | https://webbkarta.gagnef.se/spatialmap |  |  |  |  | Geosecma SpatialMap (spatialsuite 4.5.1); kommunens sida säger att detaljplaner kan sökas … |
| 2085 | Ludvika | origo | https://karta.ludvika.se/ |  |  |  |  | Ludvikakartan (Origo) ska enligt kommunen visa gällande detaljplaner, men index.json svara… |
| 2161 | Ljusdal | wms | https://kommunkarta.ljusdal.se/wms?servicename=csm_standard_profile&se… | theme-detaljplaner / theme-detaljplaner-… |  |  |  | WMS-lagret 'Gällande detaljplaner' är queryable=0; GetFeatureInfo ger LayerNotDefined. Ing… |
| 2282 | Kramfors | wms | https://map.kramfors.se/wms?servicename=plandirekt&request=GetCapabili… | theme-dp-mosaik-detaljplomr / theme-dp-b… |  |  |  | 'Kramforskartan' = Sokigo CSM 4.5.1 (Spatial Suite) med PlanDirekt-profil (profile=plandir… |
| 2313 | Strömsund | wms | https://karta.stromsund.se/wms?servicename=oversiktsplan&request=GetCa… | lm_detaljplan / cartesia-lmv-pbr-detaljp… |  |  |  | Sokigo CSM 4.4.0 (Spatial Suite). Enda publika profil som hittades är 'oversiktsplan' (län… |
| 2361 | Härjedalen | mycarta | https://karta.berg.se/#m=detaljplaner_hk |  |  |  |  | herjedalen.se länkar 'detaljplanekarta' till karta.berg.se/#m=detaljplaner_hk (myCarta Web… |
| 2403 | Bjurholm | arcgis | https://portal.bjurholm.se/portal/home/ |  |  |  |  | ArcGIS Enterprise 'Gaida Portal för Bjurholms kommun' (portal.bjurholm.se, REST-rot /arcgi… |
| 2404 | Vindeln | arcgis | https://kartportal.vindeln.se/arcgis/rest/services/Hosted/Andringsomra… | Andringsomraden | 147 |  | fd_planb, dnr | ArcGIS Enterprise 'Gaida Portal för Vindelns kommun' (kartportal.vindeln.se, alias gis.vin… |
| 2421 | Storuman | wms | https://karta.storuman.se/wms?servicename=plandirekt&request=GetCapabi… | theme-msbn_planytor |  |  |  | Sokigo CSM 4.5.1 (Spatial Suite) PlanDirekt-profil, länkad från storuman.se/gallande-detal… |
| 2460 | Vännäs | arcgis | https://kartportal.vannas.se/portal/home/index.html |  |  |  |  | ArcGIS Enterprise 'Gaida Portal för Vännäs kommun' (kartportal.vannas.se, REST-rot /arcgis… |
| 2481 | Lycksele | wms | https://webbkarta.lycksele.se/wms?servicename=plandirekt&request=GetCa… | theme-dp-mosaik-planomrade |  |  |  | 'Lyckseles publika karta' = Sokigo CSM 4.3.0 (Spatial Suite). PlanDirekt-profil (servicena… |
| 2560 | Älvsbyn | arcgis | https://gisportal.alvsbyn.se/portal/ |  |  |  |  | ArcGIS Enterprise 'Älvsbyns Kartportal' (gisportal.alvsbyn.se, REST-rot /arcgis/rest/servi… |

## E. Inget hittat (28)

| Kod | Kommun | Typ | Endpoint | Lager | Antal | Länkfält | Akt-fält | Anteckning |
|---|---|---|---|---|---|---|---|---|
| 0563 | Valdemarsvik |  |  |  |  |  |  | Ingen kartvisare hittad (inga kart-hostnamn, kommunens kartsida länkar bara till Lantmäter… |
| 0582 | Söderköping |  |  |  |  |  |  | Ingen kartvisare hittad (inga kart-hostnamn, inga länkar från startsidan). Planhandlingar … |
| 0760 | Uppvidinge |  | https://detaljplaner.lantmateriet.se/ |  |  |  |  | Ingen egen karttjänst. Hänvisar till Lantmäteriets detaljplanevisare (räknas ej) samt PDF-… |
| 1060 | Olofström |  |  |  |  |  |  | Gällande detaljplaner publiceras som PDF-lista (plankarta + planbeskrivning) på olofstrom.… |
| 1438 | Dals-Ed | download | https://www.dalsed.se/bygga-bo-och-miljo/bygga-och-bo/oversiktsplan-oc… |  |  |  |  | Endast PDF-lista per ort (Ed ca 20 planer, Nössemark 4, landsbygd 2) under /media/. Ingen … |
| 1444 | Grästorp | download | https://www.grastorp.se/bygga-bo-och-miljo/detaljplanering/lagakraftvu… |  |  |  |  | Webbsidan listar bara nyligen lagakraftvunna planer som undersidor. Göliska GIS-portal (ge… |
| 1460 | Bengtsfors | download | https://www.bengtsfors.se/bygga-bo-och-miljo/samhallsutveckling/gallan… |  |  |  |  | Gällande detaljplaner som webbsidor per ort (Bengtsfors 30 st, Billingsfors, Bäckefors, Da… |
| 1492 | Åmål |  |  |  |  |  |  | Ingen karttjänst eller planarkiv med karta hittad på amal.se (sidan Kart, mät och GIS sakn… |
| 1760 | Storfors |  |  |  |  |  |  | Endast sidor om pågående planarbete, ingen karta eller lista över gällande planer hittad. |
| 1766 | Sunne |  |  |  |  |  |  | Gällande detaljplaner publiceras som sidlista/PDF under 'Samlade planritningar'; ingen kar… |
| 1782 | Filipstad |  |  |  |  |  |  | Lista över planer med laga kraft från 2018 som webbsidor/PDF; äldre planer via kontakt. In… |
| 1783 | Hagfors |  |  |  |  |  |  | Kartsidan hänvisar till Lantmäteriets Min karta; detaljplanesidan har enstaka PDF:er. Inge… |
| 1862 | Degerfors |  |  |  |  |  |  | Gällande detaljplaner publiceras som PDF-lista (plankarta/planbeskrivning per plan). Ingen… |
| 2021 | Vansbro |  |  |  |  |  |  | Sidan 'Översikt av detaljplaner och områdesbestämmelser' är en lista; ingen karttjänst hit… |
| 2023 | Malung-Sälen |  |  |  |  |  |  | Antagna/lagakraftvunna planer publiceras som sidor med plankarta/planbeskrivning-PDF; inge… |
| 2283 | Sollefteå | origo | https://karta.solleftea.se/bxkarta/ |  |  |  |  | karta.solleftea.se är samma Sundsvall-hostade Origo-server som Härnösand (identisk index.j… |
| 2303 | Ragunda | mycarta | https://kartor.ragunda.se/ |  |  |  |  | kartor.ragunda.se är myCarta WebMap (Aveki); myCarta Server (https://kartor.ragunda.se/myc… |
| 2305 | Bräcke |  |  |  |  |  |  | Endast PDF-lista med detaljplaner antagna från 2019 på bracke.se (plankarta/planbeskrivnin… |
| 2401 | Nordmaling | arcgis | https://portal.nordmaling.se/portal/ |  |  |  |  | ArcGIS Enterprise 'Gaida Portal för Nordmalings kommun' (portal.nordmaling.se, REST-rot /a… |
| 2409 | Robertsfors |  |  |  |  |  |  | Endast PDF-lista (plankarta/planbeskrivning per plan) på robertsfors.se; äldre planer best… |
| 2417 | Norsjö | mycarta | https://karta.norsjo.se/webmap/ |  |  |  |  | karta.norsjo.se är myCarta WebMap med admin-API (https://karta.norsjo.se/Webmap/api/Map) s… |
| 2418 | Malå |  |  |  |  |  |  | mala.se hänvisar till Lantmäteriets detaljplaner.lantmateriet.se för digitala planer; i öv… |
| 2422 | Sorsele | mycarta | https://karta.sorsele.se/Webmap/ |  |  |  |  | karta.sorsele.se myCarta WebMap (admin-API https://karta.sorsele.se/Webmap/api/Map) har tr… |
| 2425 | Dorotea |  |  |  |  |  |  | PDF-lista 'Lagakraftvunna planer' på dorotea.se; inga kart-värdnamn svarar (kartportal/kar… |
| 2462 | Vilhelmina |  |  |  |  |  |  | vilhelmina.se listar antagna planer som PDF; portal.vilhelmina.se svarar 403. Planarkiv: h… |
| 2463 | Åsele |  |  |  |  |  |  | asele.se listar lagakraftvunna planer/planer under arbete som PDF; inga kart-värdnamn svar… |
| 2506 | Arjeplog |  |  |  |  |  |  | arjeplog.se: 'Kommunens detaljplaner och områdesbestämmelser finns tyvärr inte i dagsläget… |
| 2583 | Haparanda |  |  |  |  |  |  | Gällande detaljplaner publiceras som PDF-listor per område (Haparanda centralort, Nikkala,… |
