import os

import requests
from bs4 import BeautifulSoup as bs
from bs4 import SoupStrainer as ss

DATABASE_URL = "https://dynonavionics.com/us-aviation-obstacle-data.php"
DOWNLOAD_PATH = "/Users/GFahmy/Documents/RV-7/Software/test_software"


# New function: download_dynon_databases_only
def download_dynon_databases_only(
    database_url=DATABASE_URL, download_path=DOWNLOAD_PATH
):
    """
    Downloads ONLY the aviation and obstacle database (.duc) files from Dynon.
    """
    print("\nDownloading Dynon Aviation & Obstacle Databases Only")
    try:
        db_urls = [
            link["href"]
            for link in bs(
                requests.get(database_url).content,
                "html.parser",
                parse_only=ss("a"),
            )
            if ".duc" in link.get("href")
        ]
        if not db_urls:
            # print("No database files found.")
            return
        for link in db_urls:
            file = link.split("/")[-1]
            filename = os.path.join(download_path, file)
            download_url = f"https://dynonavionics.com{link}"
            # print(f"\nDownloading {file}...")
            with open(filename, "wb+") as out_file:
                content = requests.get(download_url, stream=True).content
                out_file.write(content)
            # print(f"Saved {file}")
    except Exception:
        pass
