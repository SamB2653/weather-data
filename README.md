# Example AI Workflow:

#### Baseline (Human) [src/weather.py]
Simple script created by myself

Sources:
* https://osdatahub.os.uk/
* https://datahub.metoffice.gov.uk/


#### CODEX Prompt (GPT 5.3 Codex) [src/weather_codex.py]
```
Generate python code
Input UK postcode 
Output weather forcast for the postcode 
Give the change of rain that day for the next week
Append weather_codex.py, do not alter other files
Use Python3.12 best practices
```

#### Claude Prompt (Sonnet 4.6) [src/weather_claude.py]
```
Generate python code
Input UK postcode 
Output weather forcast for the postcode 
Give the change of rain that day for the next week
Append weather_claude.py, do not alter other files
Use Python3.12 best practices
```

#### CODEX Prompt (GPT 5.3 Codex) [src/weather_codex_prompt.py]
```
Generate python code
Input UK postcode 
Output weather forcast for the postcode for 7 days 
Give the change of rain that day for the next week
Append weather_codex_prompt.py, do not alter other files
Use Python3.12 best practices https://peps.python.org/pep-0008/
Use the MET Office API for weather information https://datahub.metoffice.gov.uk/
Use the OSD API for postcodes lookup https://osdatahub.os.uk/
Both API are on free tier usage
OSD coordinates will need converting to to latitude longitude for the MET office API
The API Keys are stored in .env and are not to be exposed in the main code
Usage src/weather_codex_prompt.py "<POSTCODE>"
```

#### Baseline (Human + GPT 5.3 Codex) [src/weather_improved.py]
AI used to help debug and improve the existing script. For the example error handling and debugging.

Error checking:
> * The postcode lookup validation is too strict. It currently requires fields like POPULATED_PLACE, REGION, and COUNTRY.
If OS Data Hub returns valid coordinates but one of those fields is missing, the script fails even though it could still fetch the forecast.
>
> * The forecast field handling is inconsistent. The forecast function supports a custom field name, but the print logic always reads dayProbabilityOfRain.
If the field is changed, output will show incorrect values (N/A) even when data exists.


# Issue 1 - Code Source:

A large part of the code output is sourced from this github repo:
https://github.com/pwcazenave/pml-git/blob/master/python/osgb.py


![alt text](img/Git_README.png)

#### Example 1 - [en_to_lat_lon_osgb36]:
AI Output:
![alt text](img/codeblock1_ai_output.png)

Github Source:
![alt text](img/codeblock1_git_output.png)

#### Example 2 - [en_to_lat_lon_osgb36]:
AI Output:
![alt text](img/codeblock2_ai_output.png)

Github Source:
![alt text](img/codeblock2_git_output.png)

When a unique task is being solved using an LLM it is far more likely to generate blocks of code completely copied from training data. This can come from user inputs that the LLMs are trained on or other sources such as scraped github repositories.

# Issue 2 - Code Complexity and Maintainability:
Examples of issues:
* get_weekly_forecast() - Difficult to read and debug the API request
* format_forecast() - Convoluted print statements for output 
* en_to_lat_lon_osgb36() - Complex maths to understand and validate
* osgb36_to_wgs84() - Complex maths to understand and validate
* http_get_json() - Not needed, there are inbuilt .json functions
* Hardcoded variables such as "SIGNIFICANT_WEATHER_CODES"

The LLM regularly generates overly complex code for the solution, this code will be difficult to maintain and debug. This can be dangerous when not fully understanding the impact and reasoning of the code for its specific function.
