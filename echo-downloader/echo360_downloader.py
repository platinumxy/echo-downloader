# This script is a modified version of the original script at ETH Zurich
# found here:
# https://gitlab.ethz.ch/tgeorg/vo-scraper/-/blob/master/vo-scraper.py
# It is licensed under the GNU GPLv3 license.
import argparse
from datetime import datetime
import logging
import shutil
import sys
import os
import getpass
import random
import re
from typing import Optional, TypedDict, List
import requests

from auth import *
from utils import * 

class TargetVideo:
    """A structure for a scraped video that hasn't been downloaded yet."""

    filename: str
    video_src_link: str
    episode_name: str
    title: str
    date: datetime

    def __init__(
        self,
        filename: str,
        video_src_link: str,
        episode_name: str,
        title: str,
        date: datetime,
    ):
        self.filename = filename
        self.video_src_link = video_src_link
        self.episode_name = episode_name
        self.title = title
        self.date = date

    def __repr__(self) -> str:
        return f'TargetVideo(filename="{self.filename}", video_src_link="{self.video_src_link}", episode_name="{self.episode_name}", title="{self.title}", date="{self.date}")'

def scrape_videos(link: str, session: requests.Session) -> List[TargetVideo]:
    syllabus_link = create_syllabus_link(link)
    if not syllabus_link:
        logger.error("URL format is not valid.")
        return []

    # Try to get it on the first try, if it fails, try logging in
    r = session.get(syllabus_link)
    if "login.echo360.org.uk" in r.url:
        if not auth_echo360(session, link):
            logger.error("Could not log into EASE (invalid credentials?).")
            return []
        r = session.get(syllabus_link)

    # Attempt to parse response as JSON, which might fail if the second attempt
    # to get the syllabus page failed.
    try:
        response = r.json()
    except ValueError:
        logger.error("Could not parse JSON response.")
        return []

    # Sanity-check: Check if the JSON response says it's OK
    if "status" not in response or response["status"] != "ok":
        logger.error(f"Could not get lecture syllabus: {response['status']}")
        return []

    # Loop through each lecture recording
    targets: List[TargetVideo] = []
    for i, lecture_session in enumerate(response["data"]):
        # Make sure the fields we need are present
        if (
            lecture_session["type"] != "SyllabusLessonType"
            or "lesson" not in lecture_session
            or "lesson" not in lecture_session["lesson"]
            or "medias" not in lecture_session["lesson"]
        ):
            logger.debug(
                f"Skipping {lecture_session['lesson']['name']}: Invalid format."
            )
            continue

        # Just a bunch of sanity checking
        if not lecture_session["lesson"].get("isPast", False):
            logger.debug(
                f"Skipping {lecture_session['lesson']['lesson']['name']}: Not past."
            )

        if not lecture_session["lesson"].get("hasContent", False):
            logger.debug(
                f"Skipping {lecture_session['lesson']['lesson']['name']}: No content."
            )

        if not lecture_session["lesson"].get("hasVideo", False):
            logger.debug(
                f"Skipping {lecture_session['lesson']['lesson']['name']}: No video."
            )

        # Make sure there's at least one media because we'd make unnecessary
        # requests otherwise
        medias = lecture_session["lesson"]["medias"]
        if len(medias) == 0:
            logger.debug(
                f"Skipping {lecture_session['lesson']['lesson']['name']}: No media."
            )

        # Get the ID and send request to get the video link for the best media
        lecture_id = lecture_session["lesson"]["lesson"]["id"]

        # Print some dots to indicate progress. These will break if the scraping
        # logs something, but that's fine since it'll only happen if something
        # is wrong.
        sys.stdout.write(f"\rGetting metadata and video links" + "." * i)
        sys.stdout.flush()
        targets += scrape_videos_for_lecture(lecture_id, session)

    return targets

def scrape_videos_for_lecture(
    lecture_id: str,
    session: requests.Session,
) -> List[TargetVideo]:
    r = session.get(f"https://echo360.org.uk/lesson/{lecture_id}/media")

    # Attempt to parse response as JSON
    try:
        response = r.json()
    except ValueError:
        logger.error(f"Could not parse JSON response for lecture {lecture_id}.")
        return []

    # Sanity-check: Check if the JSON response says it's OK
    if "status" not in response or response["status"] != "ok":
        logger.error(f"Could not get videos for {lecture_id}: {response['status']}")
        return []

    # Make sure video-related fields are present
    if (
        len(response["data"]) == 0
        or "video" not in response["data"][0]
        or "media" not in response["data"][0]["video"]
        or response["data"][0]["video"]["media"].get("status", "") != "Processed"
        or "media" not in response["data"][0]["video"]["media"]
        or "current" not in response["data"][0]["video"]["media"]["media"]
    ):
        logger.debug(f"Skipping {lecture_id}: Lecture doesn't have videos.")
        return []

    # Make sure metadata is present
    if (
        "userSection" not in response["data"][0]
        or "sectionNumber" not in response["data"][0]["userSection"]
    ):
        logger.debug(f"Skipping {lecture_id}: Lecture has no metadata.")
        return []

    course_title = response["data"][0]["userSection"]["sectionNumber"]

    lecture_title = response["data"][0]["video"]["media"].get("name", "Lecture")

    # fromisoformat() with the Z timezone requires Python 3.11+, so just replace
    # the Z with +00:00
    video_date = datetime.fromisoformat(
        response["data"][0]["video"]["media"]["createdAt"].replace("Z", "+00:00")
    )

    # Each media object is structured like:
    # {
    # "s3Url": "https://content.echo360.org.uk/unique-url/1/name.extension",
    # "width": 480,
    # "height": 270,
    # "size": 59407080
    # }
    MediaJsonType = TypedDict(
        "MediaJsonType", {"s3Url": str, "width": int, "height": int, "size": int}
    )

    # Get both camera tracks if possible.
    primary_media: List[MediaJsonType] = response["data"][0]["video"]["media"][
        "media"]["current"].get("primaryFiles", [])
    secondary_media: List[MediaJsonType] =  response["data"][0]["video"]["media"][
        "media"]["current"].get("secondaryFiles", [])

    # Select largest video (per track) by resolution, and resoapp_idlve ties with larger filesize
    for media in [primary_media, secondary_media]:
        media.sort(key=lambda media: (media["height"], media["size"]), reverse=True)

    video_id = response["data"][0]["video"]["media"]["media"]["current"][
        "mediaId"].split("-")[0]
    
    videos_to_return = []
    for track_label, track_media in [("primary", primary_media), ("secondary", secondary_media)]:
        if track_media:
            videos_to_return.append(
                TargetVideo(
                    filename=remove_illegal_characters(course_title)
                    + os.sep
                    + remove_illegal_characters(
                        video_date.strftime("%Y-%m-%d") + "-" + video_id +
                         ("-" + track_label if primary_media and secondary_media else "") + ".mp4"
                    ),
                    video_src_link=track_media[0]["s3Url"],
                    title=lecture_title + (" [" + track_label + "]" if primary_media and secondary_media else ""),
                    date=video_date,
                    episode_name=video_date.strftime("%Y-%m-%d") + " " + lecture_title +
                        (" [" + track_label + "]" if primary_media and secondary_media else ""),
                )
            )

    return videos_to_return

def create_syllabus_link(link: str) -> Optional[str]:
    """Accept any link to a course on Echo360 and return the link to the JSON
    syllabus page.

    Parameters
    ----------
    link : str
        Any URL matching Echo360.org.uk/section/<uuid>, with optionally some
        other stuff after it.

    Returns
    -------
    Optional[str]
        The link to the JSON syllabus page, or None if the link is not valid.
    """
    pat = re.compile(r"https?\:\/\/echo360\.org\.uk\/section\/([A-Za-z0-9-]+)(\/.*)?")
    match = re.match(pat, link)
    if match:
        return f"https://echo360.org.uk/section/{match.group(1)}/syllabus"

    return None

def pretty_print_videos(
    videos: List[TargetVideo], filters: Optional[List[int]] = None
) -> None:
    """Prints a list of videos in a nice format.

    Parameters
    ----------
    videos : List[TargetVideo]
        List of videos to print.
    filters : Optional[List[int]], optional
        List of indices of videos to show. If None, all videos will be shown,
        and if empty list, no videos will be shown.
    """
    if len(videos) == 0:
        return

    nr_length = len(" Nr.")
    max_date_len = max([len(video.date.strftime("%Y-%m-%d")) for video in videos])
    max_title_len = max([len(video.title) for video in videos])

    # Print header first
    logger.info(
        " Nr."
        + " | "
        + "Date".ljust(max_date_len)
        + " | "
        + "Title".ljust(max_title_len)
    )

    for i, video in enumerate(videos):
        # Skip if filters are specified and this video is not in them
        if filters is not None and i not in filters:
            continue

        # Show indices if we're showing all videos, otherwise only show a star
        # to indicate that this video is selected
        nr = Colors.WARNING + "  * " + Colors.ENDC if filters else f"{i:3d}"
        logger.info(
            nr.ljust(nr_length)
            + " | "
            + video.date.strftime("%Y-%m-%d").ljust(max_date_len)
            + " | "
            + video.title.ljust(max_title_len)
        )

def interactive_video_selection(
    available_videos: List[TargetVideo],
) -> List[int]:
    """Interactively asks the user which videos to download, returns the indices
    for selected videos.

    Parameters
    ----------
    available_videos : List[TargetVideo]
        Videos to select from.

    Returns
    -------
    List[int]
        Indices of selected videos.
    """
    while True:
        user_input = input(
            "Enter numbers of the above lectures you want to download separated by "
            "space (e.g. 0 5 12 14)\nYou can also write ranges as X-Y (e.g. 0-5 8)."
            "\nJust press enter if you don't want to download anything.\n"
        ).split()

        # Parse the user input
        selection: List[int] = []
        for item in user_input:
            # Check if it's a range
            if "-" in item:
                try:
                    start, end = item.split("-")
                    selection += list(range(int(start), int(end) + 1))
                except ValueError:
                    logger.warning(f"Invalid range: {item}")
                    break
            else:
                try:
                    selection.append(int(item))
                except ValueError:
                    logger.warning(f"Invalid number: {item}")
                    break

        # No problem with parsing, so stop asking
        else:
            break

    # Make elements unique
    selection = list(set(selection))

    # Sort them, to download in order and not randomly
    selection = sorted(selection)

    return selection

def remove_illegal_characters(file_name: str) -> str:
    """Remove characters that the file system doesn't like, including slashes.
    This function should be used for individual components of a path, not on the
    entire path.

    Parameters
    ----------
    file_name : str
        File name to remove illegal characters from.

    Returns
    -------
    str
        Sanitized file name.
    """
    illegal_chars = '?<>:*|"^/\\'
    for c in illegal_chars:
        file_name = file_name.replace(c, "")
    return file_name

def download(
    file_name: str,
    video_src_link: str,
    episode_name: str,
    hide_progress_bar: bool,
    session: requests.Session,
) -> None:
    # Create directory for video if it does not already exist
    directory = os.path.dirname(os.path.abspath(file_name))
    if not os.path.isdir(directory):
        os.makedirs(directory)
        logger.debug("This folder was generated: " + directory)
    else:
        logger.debug("This folder already exists: " + directory)

    # Check if file already exists
    if os.path.isfile(file_name):
        logger.info("Download skipped - file already exists: " + episode_name)
        return

    # cf.: https://stackoverflow.com/questions/15644964/python-progress-bar-and-downloads
    with open(file_name + ".part", "wb") as f:
        response = session.get(video_src_link, stream=True)
        total_length = response.headers.get("content-length")

        logger.info(
            f"Downloading {episode_name} ({int(total_length or 0) / 1024 / 1024:.2f} MiB)"
        )

        if total_length is None or hide_progress_bar:
            # We received no content length header...
            # ... or user wanted to hide the progress bar
            f.write(response.content)
        else:
            # Download file and show progress bar
            total_length = int(total_length)

            try:
                # Module with better progressbar
                from tqdm import tqdm

                # Setup progressbar
                pbar = tqdm(
                    unit="B", unit_scale=True, unit_divisor=1024, total=total_length
                )
                pbar.clear()

                # Download to file and update progressbar
                for data in response.iter_content(chunk_size=4096):
                    pbar.update(len(data))
                    f.write(data)
                # Close it
                pbar.close()

            # If tqdm is not installed, fallback to self-made version
            except ModuleNotFoundError:
                logger.debug(
                    "Optionally dependency tqdm not installed, falling back to built-in progressbar"
                )
                dl = 0
                for data in response.iter_content(chunk_size=4096):
                    dl += len(data)
                    f.write(data)
                    progressbar_width = shutil.get_terminal_size().columns - 2
                    done = int(progressbar_width * dl / total_length)
                    sys.stdout.write(
                        f"\r[{'=' * done}{' ' * (progressbar_width - done)}]"
                    )
                    sys.stdout.flush()
    print()

    # Remove `.part` suffix from file name
    os.rename(file_name + ".part", file_name)
    logger.info("Downloaded file: " + episode_name)
