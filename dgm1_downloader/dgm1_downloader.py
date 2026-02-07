# -*- coding: utf-8 -*-
"""
Created on Sat Feb  7 14:12:38 2026

@author: max_d
"""

# Automatisierter Download des DGM1 mit einem Shape als Grundlage

import os
import geopandas as gpd
import urllib.request
from urllib.parse import urlsplit, parse_qs, unquote
from typing import Optional
from pathlib import Path
import subprocess
import rasterio
from rasterio.mask import mask



#Ordner erstellen -> als Zwischenspeicher und für Exporte später
os.makedirs("data/raw_data/downloads", exist_ok = True)
os.makedirs("data/exporte", exist_ok = True)

crs_ziel = 25832 #als Variable vermeidet man so Tippfehler

# Massendownloadershape (GeoJSON) vom Downloadportal SH herunterladen:
url = "https://geodaten.schleswig-holstein.de/gaialight-sh/_apps/dladownload/single.php?file=DGM1_SH__Massendownload.geojson&id=4" # downloadlink für Auswahlshape DGM1
ziel_massdownloader = "data/raw_data/massendownloader_dgm1.geojson"

urllib.request.urlretrieve(url, ziel_massdownloader)

print("Download des Massendownloader-Shapes für das DGM1...")
massendownloader = gpd.read_file("data/raw_data/massendownloader_dgm1.geojson") #Ressource für die Downloadlinks
print(f"CRS Massendownloader: {massendownloader.crs}")

crs_massendownloader_raw = massendownloader.crs.to_epsg() if massendownloader.crs else None

if crs_massendownloader_raw != crs_ziel:
    print(f"Transformiere CRS von {crs_massendownloader_raw} --> {crs_ziel} ...")
    massendownloader = massendownloader.to_crs(epsg=crs_ziel)
    print(f"Neues CRS: {massendownloader.crs}")
else:
    print("CRS Massendownloader stimmt.")
    
# Jetzt das Shape laden, innerhalb dessen das DGM1 heruntergeladen werden soll:
shape_ug = gpd.read_file(r"bsp_shape.geojson") #muss EPSG 25832 sein
print(f"CRS shape_ug: {shape_ug.crs}")


if shape_ug.crs.to_epsg() != crs_ziel:
    shape_ug = shape_ug.to_crs(epsg=crs_ziel) #sicherstellen, dass shape_ug auch wirklich epsg 25832 hat
    
# Die relevanten Zellen des DGM1 auswählen
auswahl_fuer_dgm1 = gpd.clip(massendownloader, shape_ug)

# Liste mit den Downloadlinks für die Zellen des DGM1 erstellen:
liste_downloadlinks_dgm1 = []

liste_downloadlinks_dgm1.extend(
    auswahl_fuer_dgm1["link_data"] #Das zieht alle Downloadlinks aus dem Shape
    .dropna() #NA-Values rausfiltern
    .unique() #duplikate entfernen
)

# Hier sollen die einzelnen .xyz Dateien gespeichert werden.
ziel_dgm1_zellen = Path("data/raw_data/downloads")

# Das zieht den Dateinamen aus dem Link:
def dateiname_aus_url(url: str) -> Optional[str]:
    split = urlsplit(url) #zerlegt die url in ihre Bestandteile -> https, website, datei usw
    qs = parse_qs(split.query) #erstellt aus den bestandteilen listen -> daraus hoilt man sich dann später den Dateinamen
    raw = qs.get("file", [None])[0] # Greift den Dateinamen aus der Liste ab
    
    if raw:
        return unquote(raw) #wenn raw existiert -> also ein Dateiname da ist, alles in Butter, es geht weiter
    
    # Der ganze Basename-kram ist nur als "notfall-plan" gedacht, falls in der url kein klarer dateiname erkennbar ist
    basename = os.path.basename(split.path) #zieht Dateinamen aus Pfad -> falls die URL nichts ergibt
   
    if basename:
        return unquote(basename) # Wenn Name vorhanden, gehts weiter, sonst skip
    
    return None
print("Dateinamen extrahiert, Download folgt...")
 
#Das läd die einzelnen Dateien herunter:
for link in liste_downloadlinks_dgm1:
    name = dateiname_aus_url(link)
    ziel_pfad = ziel_dgm1_zellen/name
    urllib.request.urlretrieve(link, ziel_pfad)
    print(f"Download erledigt: {ziel_pfad}")
    
    subprocess.run([
        "gdal_translate",
        "-a_srs", f"EPSG:{crs_ziel}",
        str(ziel_pfad),
        str(ziel_pfad.with_suffix(".tif"))
        ], check=True)

print("Download der Einzeldateien abgeschlossen.")

print("Das kann jetzt ganz schön lange dauern...")
#Jetzt die Downloads in eine Datei mergen:
xyz_pfad = Path("data/raw_data/downloads") #ausgangsdateien
vrt_pfad = Path("data/exporte/dgm1_mosaik.vrt")
tif_pfad = Path("data/exporte/dgm1_merged.tif") #Zieldatei

#VRT Mosaik erstellen (Bauplan für das eigentlich Tif)
subprocess.run([
    "gdalbuildvrt",
    str(vrt_pfad),
    *[str(p) for p in sorted(xyz_pfad.glob("*.xyz"))],
    ], check = True)

print("VRT-Mosaik erstellt.\nJetzt dauert es wieder eine Weile...")

# jetzt aus dem VRT ein GeoTIFF machen:
subprocess.run([
    "gdal_translate",
    "-a_srs", f"EPSG:{crs_ziel}",
    str(vrt_pfad),
    str(tif_pfad)
    ], check = True)

print(f"GeoTiff: {tif_pfad} erstellt.")

print("GeoTiff croppen...")
# Tif an shape croppen:
## Zuerst geometrien aus shape_ug absammeln:
geometrien = [geom for geom in shape_ug.geometry]

##dann tif öffnen und los:
with rasterio.open(tif_pfad) as src:
    out_image, out_transform = mask(src, geometrien, crop = True)
    out_meta = src.meta.copy()

#meta daten für export anpassen:
out_meta.update({
    "driver": "GTiff",
    "height": out_image.shape[1],
    "width": out_image.shape[2],
    "transform": out_transform
})

# Fertige Datei exportieren:
output_pfad = "data/exporte/DGM1_cropped.tif"
with rasterio.open(output_pfad, "w", **out_meta) as dest:
    dest.write(out_image)

print("Skript fertig :)")