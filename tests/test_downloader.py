import os
import unittest
from datetime import datetime

import pytest
from pathlib import Path

from ricecooker.utils import downloader
import http.server
from threading import Thread
import shutil

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
        sushi_url = "http://localhost:" + str(PORT) + "/samples/PreTeXt_book_test/activecalculus.org/single2e/sec-5-2-FTC2.html"
        dest_dir = "active_calc_2e_again_" + datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
        current_file_dir = Path(__file__).resolve().parent
        downloads_dir = current_file_dir.parent / "downloads"
        try:
            archive = downloader.ArchiveDownloader("downloads/" + dest_dir)
            archive.get_page(sushi_url)

            book_dest_dir = downloads_dir / dest_dir / "localhost:8181" / "samples" / "PreTeXt_book_test"
            with open(book_dest_dir / "activecalculus.org" / "single2e" / "sec-5-2-FTC2.html", 'r') as file:
                page_html = file.read()
                assert "link href=\"../../fonts.googleapis.com/css2_family" in page_html

            with open(book_dest_dir / "fonts.googleapis.com" / "css2_family_Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0" / "index.css", 'r') as file:
                css_file_contents = file.read()
                assert "src: url(\"../../fonts.gstatic.com/s/materialsymbolsoutlined" in css_file_contents

            font_size = os.path.getsize(book_dest_dir / "fonts.gstatic.com" / "s" / "materialsymbolsoutlined" / "v290" / "kJF1BvYX7BgnkSrUwT8OhrdQw4oELdPIeeII9v6oDMzByHX9rA6RzaxHMPdY43zj-jCxv3fzvRNU22ZXGJpEpjC_1v-p_4MrImHCIJIZrDCvHOel.woff")
            assert font_size > 0
        finally:
            shutil.rmtree(downloads_dir / dest_dir)
