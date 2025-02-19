#!/bin/python3


import json
import requests
import schedule
import sys
import time
import yaml
import datetime
from datetime import datetime as datetime2

from pprint import pprint
# Local imports
from enums import Enums
from core import Core
from discordStyles import DiscordStyle

Vdebug = False

def debug(valname, val):
    global Vdebug
    if Vdebug:
        print(f"{valname}:")
        if isinstance(val, map):
            pprint(list(val))
        else:
            pprint(val)


def load_config():
    global Vdebug
    print("Loading config..")
    config = {}
    try:
        with open(sys.argv[1], "r") as configFile:
            config = yaml.load(configFile, Loader=yaml.FullLoader)
    except Exception:
        sys.exit("Error loading config!")

    if config.get("debug"):
        Vdebug = True

    debug("config", config)
    print("Done loading config!")
    return config


def writeRankToFile(rank, queue, summonerId):
    path = Core.OSJoin("tmp",f"{summonerId}.{queue}.rank")
    with open(path, encoding="utf-8", mode="w") as file:
        file.write(rank)


def readRankFromFile(summonerId, queue):
    path = Core.OSJoin("tmp",f"{summonerId}.{queue}.rank")
    try:
        with open(path, encoding="utf-8", mode="r") as file:
            jsonData = json.loads(file.read())
            return jsonData
    except FileNotFoundError:
        print(f"The rank file for {summonerId}.{queue} doesn't exist yet")
        return None


def createDiscordMessage(currentRank, oldRank, matchData):
    (isTierChanged, isRankChanged, isLpChanged) = getRankChanges(oldRank, currentRank)

    ds = DiscordStyle()

    discordMessageName = currentRank['summonersName']
    queueType = currentRank['queueType']

    queueTypeMsg = f"{ds.grayColor(queueType + ':')}"
    summonerMsg = ds.orangeColor(discordMessageName)
    message = summonerMsg

    currentRankMsg = f"{currentRank['tier']} {currentRank['rank']} {currentRank['lp']} lp"
    promotedCurrentRankMsg = f"{ds.greenColor("promoted")} from {oldRank['tier']} {oldRank['rank']} {oldRank['lp']} lp to {ds.greenColor(currentRankMsg)}"
    demotedCurrentRankMsg = f"{ds.redColor("demoted")} from {oldRank['tier']} {oldRank['rank']} {oldRank['lp']} lp to {ds.redColor(currentRankMsg)}"

    lpDifference  = calculateLpDifference(oldRank, currentRank)
    lpDifferenceMsg  = f"({lpDifference} lp)"
    blueLpDifferenceMsg = ds.lightBlueColor(lpDifferenceMsg)
    pinkLpDifferenceMsg = ds.pinkColor(lpDifferenceMsg)

    #print("debug:", discordMessageName, (isTierChanged, isRankChanged, isLpChanged))

    if(isTierChanged):
        isTierPromoted = Enums.LeagueTier[currentRank['tier']].value > Enums.LeagueTier[oldRank['tier']].value
        if(isTierPromoted):
            message = f"{queueTypeMsg} Congrats {summonerMsg} is now {promotedCurrentRankMsg} {blueLpDifferenceMsg}"
        else:
            message = f"{queueTypeMsg} {summonerMsg} is now {demotedCurrentRankMsg} {pinkLpDifferenceMsg}"

    if(isRankChanged and not isTierChanged):
        isRankPromoted = Enums.LeagueRank[currentRank['rank']].value > Enums.LeagueRank[oldRank['rank']].value
        if(isRankPromoted):
            message = f"{queueTypeMsg} Congrats {summonerMsg} is now {promotedCurrentRankMsg} {blueLpDifferenceMsg}"
        else:
            message = f"{queueTypeMsg} {summonerMsg} is now {demotedCurrentRankMsg} {pinkLpDifferenceMsg}"

    if(isLpChanged and not (isTierChanged or isRankChanged)):
        if("-" in lpDifference): # TODO this is so bad but lazy
            message = f"{queueTypeMsg} {summonerMsg} is now {currentRankMsg} {pinkLpDifferenceMsg}"
        else:
            message = f"{queueTypeMsg} {summonerMsg} is now {currentRankMsg} {blueLpDifferenceMsg}"

    ### MatchData["gameDuration"] is string in format "%H:%M:%S"
    ### Get minutes if under 18 min show FF15 message
    ff15 = datetime2.strptime(matchData["gameDuration"], '%H:%M:%S').minute < 18
    ff15Msg = "ff15, " if ff15 is True else ""

    matchInfo1 = f"Duration {ds.blueColor(matchData["gameDuration"])}, {ds.blueColor(matchData["teamPosition"])} as {ds.orangeColor(matchData["championName"])}"
    matchInfo2 = f"KDA: {ds.blueColor(matchData["KDA"])}"

    ### If Michael show Dmg
    matchInfoDmg = f"Dmg: {ds.blueColor(matchData["totalDamageDealtToChampions"])}" if matchData["summonerId"] == Enums.SummonerId.Michael.value else ""

    matchInfo = f"{ff15Msg}{matchInfo1} {matchInfo2} {matchInfoDmg}"

    payload = {
        "content": (""
            "```ansi\r\n"
            f"{message}\r\n"
            f"{ds.grayColor("Match info:")} {matchInfo}"
            "```"        
        "")
    }

    #print("debug:", payload["content"])

    return payload


def postToDiscord(discordMessageName, payload):
    headers = {
        "Content-Type": "application/json"
    }

    discordUrl = (
        "https://discord.com/api/webhooks/1090678079443181650/"
        "jBF_EhBUAG8y-uhRVYO4SeT1VeltFd0YmlN_rAS1jDB5dwRfMkBzG1u5bUJHRo8_clVa"
    )

    response = requests.post(
        discordUrl, data=json.dumps(payload), headers=headers
    )

    if response.status_code == 204:
        print(f"Message for {discordMessageName} sent successfully")
    else:
        print("Failed to send message. Status code:", response.status_code)


def getSummonersMatchData(riotApiToken, summonerId, currentRank):
    puuid = currentRank["puuid"]

    ### Get Puuid if not yet found and save it in currentRank
    if puuid is None or puuid is "":
        ### Get Summoners puuid if not found from currentRank
        responseData = Core.getLeagueApiResponse(f"summoner/v4/summoners/{summonerId}", riotApiToken)
        puuid = responseData["puuid"]
        currentRank["puuid"] = puuid
   
    ### Get summoners matches by puuid, returns list of match ids
    responseData = Core.getLeagueApiResponse(f"match/v5/matches/by-puuid/{puuid}/ids", riotApiToken, queryParameters="?start=0&count=1", region="europe")

    ### Get match information
    latestMatchId = responseData[0]
    responseData = Core.getLeagueApiResponse(f"match/v5/matches/{latestMatchId}", riotApiToken, region="europe")

    ### parse data from match response
    matchInfo = responseData["info"]
    matchDuration = matchInfo["gameDuration"]
    matchDurationStr = str(datetime.timedelta(seconds=int(matchDuration)))
    matchParticipants = matchInfo["participants"]

    if (participant := GetParticipantsByPuuid(matchParticipants, puuid)) is not None:
        teamPosition = participant["teamPosition"] if participant["teamPosition"] is not "" else participant["lane"]
        championName = participant["championName"] 
        deaths = participant["deaths"]
        assists = participant["assists"]
        kills = participant["kills"]
        totalDamageDealtToChampions = participant["totalDamageDealtToChampions"]
        totalMinionsKilled = participant["totalMinionsKilled"]
        summonerId = participant["summonerId"]

    matchData = {
                    "gameDuration": matchDurationStr,
                    "championName": championName,
                    "teamPosition": Enums.TeamPosition[teamPosition].value,
                    "KDA": f"{kills}/{deaths}/{assists}",
                    "totalDamageDealtToChampions": totalDamageDealtToChampions,
                    "totalMinionsKilled": totalMinionsKilled,
                    "summonerId": summonerId
                }

    return matchData

def GetParticipantsByPuuid(matchParticipants, puuid):
    for participant in matchParticipants:
        if participant["puuid"] == puuid:
            return participant
        
    return None


def getCurrentRank(riotApiToken, summonerId, queueType, discordMessageName, oldRank):
    responseData = Core.getLeagueApiResponse(f"league/v4/entries/by-summoner/{summonerId}", riotApiToken)
    puuid = None

    try:
        puuid = oldRank["puuid"]
    except:
        pass

    if responseData is not None:
        for queue in responseData:
            if queue["queueType"] == queueType:
                rank = {
                    "summonersName": discordMessageName,
                    "queueType": Enums.QueueType[queueType].value,
                    "tier": queue["tier"],
                    "rank": queue["rank"],
                    "lp": queue["leaguePoints"]
                }
                rank["puuid"] = "" if puuid is None else puuid
                return rank
    else:
        return None
        


def getRankChanges(oldRank, currentRank): 
    isTierChanged = Enums.LeagueTier[currentRank['tier']].value != Enums.LeagueTier[oldRank['tier']].value
    isRankChanged = Enums.LeagueRank[currentRank['rank']].value != Enums.LeagueRank[oldRank['rank']].value
    isLpChanged = oldRank["lp"] != currentRank["lp"]

    return (isTierChanged, isRankChanged, isLpChanged)


def rankChanged(oldRank, currentRank):
    if oldRank is None or currentRank is None:
        return False

    (isTierChanged, isRankChanged, isLpChanged) = getRankChanges(oldRank, currentRank)

    return isTierChanged or isRankChanged or isLpChanged


def calculateLpDifference(oldRank, currentRank):
    oldLpInt = int(oldRank['lp'])
    currentLpInt = int(currentRank['lp'])
    difference = currentLpInt - oldLpInt
    output = f"+ {difference}" if difference > 0 else f"{difference}"
    return output


def main(monitored_players):
    for player in monitored_players:
        summonerId = player['summonerId']
        discordMessageName = player['discordMessageName']
        queue = player['queue']

        oldRank = readRankFromFile(summonerId, queue)
        currentRank = getCurrentRank(riotApiToken, summonerId, queue, discordMessageName, oldRank)
        if currentRank is not None:
            if rankChanged(oldRank, currentRank):
                matchData = getSummonersMatchData(riotApiToken,summonerId, currentRank)
                dicordMessagePayload = createDiscordMessage(currentRank, oldRank, matchData)
                postToDiscord(discordMessageName, dicordMessagePayload)
            else:
                print(f"No changes for {discordMessageName} "
                    f"or file wasn't present")
            
            writeRankToFile(json.dumps(currentRank), queue, summonerId)

config = load_config()
riotApiToken = config['riotApiToken']

schedule.every(1).minutes.do(main, config['monitored_players'])
#schedule.every(10).seconds.do(main, config['monitored_players'])

while True:
    schedule.run_pending()
    time.sleep(1)
