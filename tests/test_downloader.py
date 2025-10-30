import os
import unittest
from datetime import datetime
from time import sleep

import pytest
from pathlib import Path

from ricecooker.utils import downloader
from ricecooker.utils.downloader import read
import http.server
from threading import Thread

PORT = 8181

@pytest.fixture(scope="module")
def http_local_server():
    # Get the directory containing the current file
    current_file_directory = Path(__file__).resolve().parent
    print(f"Directory of the current file: {current_file_directory}")

    test_content_path = str(current_file_directory / "testcontent")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=test_content_path, **kwargs)

    def spawn_http_server(arg):
        with  http.server.HTTPServer(("", PORT), Handler) as httpd:
            print("serving at port", PORT)
            try:
                httpd.serve_forever()
            except:
                httpd.server_close()

    server_spawning_thread = Thread(target=spawn_http_server, args=(10,))
    server_spawning_thread.daemon = True
    server_spawning_thread.start()
    return server_spawning_thread

@pytest.mark.usefixtures("http_local_server")
class TestArchiver(unittest.TestCase):

    def test_get_archive_filename_absolute(self):
        link = "https://learningequality.org/kolibri.png"

        urls_to_replace = {}
        result = downloader.get_archive_filename(
            link, download_root="./", resource_urls=urls_to_replace
        )

        expected = os.path.join("learningequality.org", "kolibri.png")

        assert result == expected
        assert urls_to_replace[link] == expected

    def test_get_archive_filename_relative(self):
        link = "../kolibri.png"
        page_link = "https://learningequality.org/team/index.html"

        urls_to_replace = {}
        result = downloader.get_archive_filename(
            link, page_url=page_link, download_root="./", resource_urls=urls_to_replace
        )

        expected = os.path.join("learningequality.org", "kolibri.png")

        assert result == expected
        assert urls_to_replace[link] == expected

    def test_get_archive_filename_with_query(self):
        link = "../kolibri.png?1.2.3"
        page_link = "https://learningequality.org/team/index.html"

        urls_to_replace = {}
        result = downloader.get_archive_filename(
            link, page_url=page_link, download_root="./", resource_urls=urls_to_replace
        )

        expected = os.path.join("learningequality.org", "kolibri_1.2.3.png")

        assert result == expected
        assert urls_to_replace[link] == expected

        link = "../kolibri.png?v=1.2.3&i=u"
        page_link = "https://learningequality.org/team/index.html"

        urls_to_replace = {}
        result = downloader.get_archive_filename(
            link, page_url=page_link, download_root="./", resource_urls=urls_to_replace
        )

        expected = os.path.join("learningequality.org", "kolibri_v_1.2.3_i_u.png")

        assert result == expected
        assert urls_to_replace[link] == expected

    def test_archive_path_as_relative_url(self):
        link = "../kolibri.png?1.2.3"
        page_link = "https://learningequality.org/team/index.html"
        page_filename = downloader.get_archive_filename(page_link, download_root="./")
        link_filename = downloader.get_archive_filename(
            link, page_url=page_link, download_root="./"
        )
        rel_path = downloader.get_relative_url_for_archive_filename(
            link_filename, page_filename
        )
        assert rel_path == "../kolibri_1.2.3.png"

    def test_pretextbook_css_fetch(self):
        sushi_url = 'https://activecalculus.org/single2e/frontmatter.html'
        archive = downloader.ArchiveDownloader("downloads/active_calc_2e_again_" + datetime.now().strftime("%Y-%m-%d_%H:%M:%S"))
        archive.get_page(sushi_url)

