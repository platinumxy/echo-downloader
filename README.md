# Echo360 Downloader

A Python 3.7+ script for UoE students to download lecture videos from [echo360.org.uk](https://echo360.org.uk/).

Multiple parts of this project's code is taken from ETH Zurich's [vo-scraper](https://gitlab.ethz.ch/tgeorg/vo-scraper/-/tree/master), which is released under the GNU GPLv3 license. The authentication code has also been adapted from [BetterInformatics](https://files.betterinformatics.com/).

Many thanks to Yuto for their work on the project before the auth changes! 


## Requirements:

 * `requests`
 * `selenium`
 * `cryptography`
 * `colorama`
 * `tqdm` (optional, gives better progressbar)


Install with:
```bash
pip3 install requests tqdm selenium cryptography colorama
```

# FAQ

### Q: How do I use it?

#### A:

    python3 echo-downloader <arguments> <course link(s)>

To see a list of possible arguments check

    python3 echo-downloader --help

**For courses that need you to be authenticated (most of them)**, the downloader will ask for your login credentials before downloading the video(s). The script does not store these credentials anywhere; It will give you the option to save and encrypt the echo360 cookies to minimize the need to re-login, you can verify this yourself by peeking at auth.py and seleinum_controler.py.

### Q: How can I choose which lecture of a course to download?

#### A: You will be prompted with the list of episodes available for downloading for each course.

You can either specify single episodes by typing their indices separated by space, or add ranges, like `1-5` for `1 2 3 4`.
Ranges are upper-bound-inclusive.

You can also use `--all` to download all lectures for a course.

### Q: Can I use it to download live streams?

#### A: No

Downloading live streams is not supported.

### Q: Can I use it to download lecture recordings from other platforms (e.g. Zoom)?

#### A: No

Downloading is only supported for recorded lectures on [echo360.org.uk](https://echo360.org.uk/). Other platforms such as Zoom, Microsoft Teams, YouTube, and Media Hopper are not supported.

### Q: How do I pass a file with links to multiple courses?

#### A: Use `--file <filename>`

The file should only have one link per line. Lines starting with `#` will be ignored and can be used for comments. Empty lines will also be ignored. It should look something like this:

    https://echo360.org.uk/section/<unique-id>/home

    # This is a comment
    https://echo360.org.uk/section/<unique-id>/
    ...

### Q: I don't like having to pass all those arguments each time I download recordings. Is there a better way?

#### A: Yes

You can can create a file called `arguments.txt` in which you put all your arguments. As long as you keep it in the same directory in which you call the downloader, it will automatically detect the file and read the arguments from there.

**Example:**

If you create a file called `arguments.txt` with the following content

```
--all
--verbose
```

and then run `python3 echo-downloader <some course link>` in that directory it will download all recordings (`--all`) from that course while spitting debug info to the console.

If you want to use a different name for the parameter file, you can pass the parameter `--arguments-file <filename>`. Ironically, you cannot do this via `arguments.txt` :P

### <a name="how_it_works"></a> Q: How does it acquire the videos?

#### A: Like so:

Each course on [echo360.org.uk](https://echo360.org.uk/) has a JSON file with metadata associated with it.

So for example

    https://echo360.org.uk/section/5158b49c-06c2-4958-a437-0ce3bd977ee6/home

has its JSON file under:

    https://echo360.org.uk/section/5158b49c-06c2-4958-a437-0ce3bd977ee6/syllabus

This JSON file contains a list of all "sessions" where the ids of all the lectures are located.

Using those ids we can access another JSON file to get the available videos for a lecture:

    https://echo360.org.uk/lesson/{lecture_id}/media

This file contains links to all available video streams (usually 720p and 270p).

So what the downloader does is get the list of sessions from the course's metadata, and then acquiring the links to the videos selected by the user by accessing the videos' JSON files. Afterwards it downloads the videos behind the links.

### Q: It doesn't work for my course. What can I do to fix it?

#### A: Follow these steps:
1. Make sure you have connection to [echo360.org.uk](https://echo360.org.uk/). The downloader should let you know when there's no connection.
2. Try running it again. Sometimes random issues can throw it off.
3. If the course is password protected, make sure you use the correct credentials. These are your EASE credentials.
4. Make sure you're running the newest version of the downloader by re-downloading the script from the repository. There might have been an update.
5. Check whether other courses still work. If none of them do, maybe the site was updated which broke the scraper.
6. Enable the debug flag with `--verbose` and see whether any of the additional information now provided is helpful.
7. Check "[How does it acquire the videos?](#how_it_works)" and see whether you can manually reach the video in your browser following the steps described there.
8. After having tried all that without success, feel free to open up a new issue. Please make sure to explain what you have tried and what the results were. If you can fix the issue yourself, feel free to open a merge request with the fix.


### Q: Can you fix *X*? Can you implement feature *Y*?

#### A: Feel free to open an issue [here](https://github.com/platinumxy/echo-downloader/issues). Merge requests are always welcome but subject to my own moderation.
