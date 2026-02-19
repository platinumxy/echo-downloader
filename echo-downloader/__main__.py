
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


from utils import *
from echo360_downloader import *

# A list of hints that randomly get displayed after the script finishes, unless
# the user disables them.
HINT_LIST: List[str] = [
    # --help
    """Want to know more about the script's functionality?
Run `python3 echo360_downloader.py --help` to see all commands that can be used.
For a detailed explanation of some of the commands, check out the README here:
https://git.tardisproject.uk/kilo/echo360-downloader""",
    # --all
    """Want to download all recordings of a lecture at once?
If you use `--all` it will skip the selection screen and download all recordings.
Usage example:

    python3 echo360_downloader.py --all https://echo360.org.uk/section/5158b49c-06c2-4958-a437-0ce3bd977ee6/home""",
    # Bug reporting
    """Found a bug?
Report it directly at https://git.tardisproject.uk/kilo/echo360-downloader/-/issues""",
    # --destination DESTINATION
    """Did you know? By default the echo360_downloader saves the dowloaded recordings in \"Lecture Recordings\" in the current directory.
If you want the recordings saved in a different place you can use the parameter `--destination <your folder>`
For example:

    python3 echo360_downloader.py --destination my_folder https://echo360.org.uk/section/5158b49c-06c2-4958-a437-0ce3bd977ee6/home

saves the recordings inside the folder name \"my_folder\"""",
    # --disable-hints
    """Getting annoyed by this hint message?
You can pass the parameter `--disable-hints` to not show hints after running.""",
    # --file FILE
    """Downloading multiple lectures and tired of having to enter all those links everytime you want to download a recording?
You can paste all your links in a text file and then tell the scraper to read from that file using the parameter `--file <your text file>`
Example:

    python3 echo360_downloader.py --file my_lectures.txt

The scraper will read the links from that file and download them as usual.""",
    # --hide-progress-bar
    """Progress bar breaking your terminal?
Hide it by passing the parameter `--hide-progress-bar`""",
    # --history-file FILE
    """Did you know, that the scraper does not re-download a lecture recording if it detects the recording in its download folder?
This way bandwidth is saved by preventing unecessary re-downloads, especially when using the `--all` parameter to download all existing recordings of a lecture.
However this also mean that if you delete the recording and run the scraper with `--all` again it will re-download the recording.

To fix this you can use the parameter `--history-file <some filename>` which creates a text file with that name and stores a history of all downloaded lectures there.
For example:

    python3 echo360_downloader.py --history-file history.txt <your links>

will create a file called 'history.txt' and save a history of all downloaded recordings there. If you delete a downloaded video the downloader will not redownload it as long as you pass `--history-file <filename> every time you run it.`""",
    # --arguments-file FILE
    """Annoyed by having to type all those parameters like `--all`, `--history-file`, etc. by hand?
You can create a text file called "arguments.txt" and paste all your parameters there. If it's in the same location as the downloader it will automatically read it and apply them.

If you want to use a different name for it, you can pass `--arguments-file <your filename>` to read parameters from `<your filename>` instead.
Ironically this parameter cannot be put into the parameter file.""",
    # --print-source [FILE]
    """Have your own method of downloading videos?
You can use the parameter `--print-source` to print the direct links to the recordings instead of downloading them.
By default the links are printed in your terminal. If you follow up the parameter with a file e.g. `--print-source video_links.txt` a file with that name is created and all the links are saved there. You may need authorization to download the videos.""",
    # --skip-connection-check
    # --skip-update-check
    """In order to ensure functionality, the scraper will check whether your version is up to date and that you have an internet connection.
If you don't like this, you can pass the parameter `--skip-update-check` to prevent the former and `--skip-connection-check` to prevent the latter.""",
    # Tardis
    """Did you know that this script is developed and hosted on Tardis?
Tardis is a part of University of Edinburgh CompSoc, and provides computing services to hobbyists and small organisations, for any non-profit purposes. Our goal is to promote small-scale computing, and provide a safe space for users to learn practical sysadmin and computing skills.

If you're interested, check out our website at https://tardisproject.uk/""",
]



parser = argparse.ArgumentParser()
parser.add_argument(
    "course_link",
    nargs="*",
    help="A link for each course on Echo360 to download videos from. Should be in the form: https://echo360.org.uk/section/<uuid>/home",
)
parser.add_argument(
    "-a",
    "--all",
    action="store_true",
    help="Download all videos of the specified course(s). Already downloaded videos will be skipped.",
)
parser.add_argument(
    "-d",
    "--destination",
    default="Lecture Recordings" + os.sep,
    help='Directory to save the downloads to. A new subdirectory will be created within it per course. By default this is "Lecture Recordings" in the current directory.',
)
parser.add_argument(
    "--disable-hints",
    action="store_true",
    help="Disable hints that get displayed when the downloader finishes.",
)
parser.add_argument(
    "-f",
    "--file",
    metavar="FILE",
    help="A file containing a list of course links to download videos from. Each line should be in the form: https://echo360.org.uk/section/<uuid>/home",
)
parser.add_argument(
    "--hide-progress-bar",
    action="store_true",
    help="Hide the progress bar when downloading videos.",
)
parser.add_argument(
    "--history-file",
    metavar="FILE",
    help="File to read/write a cache list of downloaded video IDs. The downloader will skip downloading any videos already listed here, in addition to already-existing files. By default this is not used, and downloads will be skipped only if the file exists.",
)
parser.add_argument(
    "--arguments-file",
    metavar="FILE",
    default="arguments.txt",
    help='File to read default command-line arguments from. The contents will be unioned with the command-line parameters. By default this is "arguments.txt" in the current directory.',
)
parser.add_argument(
    "-p",
    "--print-source",
    metavar="FILE",
    nargs="?",
    default=argparse.SUPPRESS,
    help="Prints the source link for each video without downloading. If a file is specified, the links will be written to that file instead. Useful for using with other downloaders.",
)
parser.add_argument(
    "-sc",
    "--skip-connection-check",
    action="store_true",
    help="Skip checking whether there's an internet connection.",
)
parser.add_argument(
    "-su",
    "--skip-update-check",
    action="store_true",
    help="Skip checking for updates for the script.",
)
parser.add_argument(
    "-v",
    "--verbose",
    action="store_true",
    help="Prints additional debugging information.",
)
parser.add_argument(
    "--version",
    action="store_true",
    help="Prints the current version of the script and exit.",
)



def main(args: argparse.Namespace) -> int:
    """Central logic of the script.

    Parameters
    ----------
    args : argparse.Namespace
        Arguments passed to the script.

    Returns
    -------
    int
        Exit code
    """
    logger.debug("This log line is only visible if --verbose flag is set.")

    if args.version:
        logging.info(VERSION)
        return 0

    links = args.course_link
    if args.file:
        with open(args.file, "r") as f:
            # Ignore empty lines and lines starting with #
            links += filter(
                lambda line: line.strip() and not line.strip().startswith("#"),
                f.read().split(),
            )

    if not links:
        logger.error("No course links specified. See --help for more information.")
        return 1

    # Check that we have an internet connection to download with
    if not args.skip_connection_check:
        try:
            requests.get("https://echo360.org.uk")
        except requests.exceptions.ConnectionError:
            logger.error("No internet connection.")
            return 1
    else:
        logger.info("Skipping internet connection check.")

    # If there are updates, we will warn but not fail
    if not args.skip_update_check:
        try:
            remote_version = requests.get(REMOTE_VERSION_URL).text.strip()
            if remote_version != VERSION:
                logger.warning(
                    f"New version available: {remote_version}. You are using {VERSION}."
                )
                logger.warning(
                    f"If you encounter issues, we recommend re-downloading the script from {REMOTE_URL}."
                )
        except requests.exceptions.ConnectionError:
            logger.warning("Could not check for updates.")
    else:
        logger.info("Skipping update check.")

    video_target_collection: List[TargetVideo] = []

    # Reuse the same session for all requests (to keep auth cookies if any).
    session = requests.Session()
    for link in links:
        # For each provided link, we'll scrape the videos available (optionally
        # asking for auth), then interactively ask the user which ones they want
        # to download.
        logger.info("Currently selected: " + link)
        if "echo360.org.uk/section" not in link:
            logger.warning(
                "Looks like the link doesn't go to 'echo360.org.uk' and therefore has been skipped. Please make sure that it is correct: "
                + link
            )

            if "youtube" in link or "youtu.be" in link:
                logger.warning(
                    "If the video is on YouTube, you can use the tools youtube-dl or yt-dlp."
                )

            continue

        available_videos = scrape_videos(link, session)
        logging.info(f"Found {len(available_videos)} videos.")

        if len(available_videos) == 0:
            continue

        pretty_print_videos(available_videos)

        # Ask the user for indices of videos to download
        selection: List[int] = []
        if args.all:
            selection = list(range(len(available_videos)))
        else:
            selection = interactive_video_selection(available_videos)

        # Confirm selection
        logger.info("Selected videos: ")
        pretty_print_videos(available_videos, filters=selection)

        # Add selected videos to the collection
        for i in selection:
            video_target_collection.append(available_videos[i])

    logger.debug(f"Videos to download: {video_target_collection}")

    for video in video_target_collection:
        if "print_source" in args:
            if args.print_source:
                logger.debug(
                    f"Printing {video.video_src_link} to file: {args.print_source}"
                )
                with open(args.print_source, "a") as f:
                    f.write(video.video_src_link + "\n")
            else:
                logger.info(video.video_src_link)
            continue

        if args.history_file:
            try:
                with open(args.history_file, "r") as f:
                    if video.video_src_link in f.read():
                        logger.info(
                            f"Skipping {video.episode_name}: Already in history.txt."
                        )
                        continue
            except FileNotFoundError:
                logger.warning("No history file found at " + args.history_file)
                logger.warning("Creating a new one.")

            with open(args.history_file, "a") as f:
                f.write(video.video_src_link + "\n")

        directory_prefix = args.destination
        logger.debug("Destination dir: " + directory_prefix)
        if not directory_prefix.endswith(os.sep):
            directory_prefix += os.sep
            logger.debug("Added missing slash: " + directory_prefix)

        download(
            directory_prefix + video.filename,
            video.video_src_link,
            video.episode_name,
            args.hide_progress_bar,
            session,
        )

    if not args.disable_hints and HINT_LIST and video_target_collection:
        logger.info("")
        logger.info("-" * shutil.get_terminal_size().columns)
        logger.info("Hint:")
        logger.info(random.choice(HINT_LIST))
        logger.info("-" * shutil.get_terminal_size().columns)

    return 0


if __name__ == "__main__":
    args = parser.parse_args()

    # Before handing the main function the CLI arguments, check if an argument
    # file was specified and if so, read it and union it with the CLI arguments,
    # with the CLI arguments taking precedence.
    if args.arguments_file != "":
        try:
            with open(args.arguments_file, "r") as f:
                args = parser.parse_args(f.read().split() + sys.argv[1:])
        except FileNotFoundError:
            pass

    # Set up so the default log level is everything above INFO. This is so that
    # we can use always use logger.info() instead of print() for normal output,
    # making the distinction less confusing for the developers.
    logging.basicConfig(
        format="%(levelname)s%(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )

    # Suppress noisy third-party library logs
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("selenium.webdriver").setLevel(logging.WARNING)
    
    # Color the log level prefixes unless the output is INFO or is piped
    logging.addLevelName(logging.INFO, f"")
    logging.addLevelName(logging.ERROR, f"{Colors.ERROR}ERROR{Colors.ENDC} ")
    logging.addLevelName(logging.WARNING, f"{Colors.WARNING}WARN{Colors.ENDC} ")
    logging.addLevelName(logging.DEBUG, f"{Colors.DEBUG}DEBUG{Colors.ENDC} ")

    logger.debug(f"Parsed Arguments: {args}")

    # Main logic
    sys.exit(main(args))
