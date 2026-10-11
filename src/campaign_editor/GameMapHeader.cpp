// GameMapHeader.cpp - the campaign editor's map header reader (h3ccmped
// 0x422640..0x424e30, between Error.cpp and GameResource.cpp; file name
// inferred). The scenario map's constructor reads each map's header through
// it. The map editor's reader is GameMap.cpp's; this copy reads its bit sets
// through the campaign editor's RawStream.h, reads the main town's location
// in each branch and fills a missing hero availability with ~TPlayerMask().
#include "campaign_editor/stdafx.h"

#include <algorithm>

#include "va.h"
#include "campaign_editor/RawStream.h"
#include "editor/BitsetIterator.h"
#include "editor/GameMapHeader.h"

// A location: three bytes, x 0xff for none.
VA(0x00422670, 0xd3)
TRawIStream& operator>>(TRawIStream& stream, TMapLoc& loc)
{
    unsigned char value;
    stream >> value;
    loc.m_x = value;
    stream >> value;
    loc.m_y = value;
    stream >> value;
    loc.m_layer = value;
    if (loc.m_x == 0xff) {
        loc.m_x = -1;
        loc.m_y = -1;
        loc.m_layer = -1;
    }
    return stream;
}

VA(0x00422750, 0x378)
void TGameMapHeader::_readVictoryCondition(TVictoryConditionData& data, TRawIStream& stream, int version)
{
    signed char value;
    stream >> value;
    data.m_type = value;
    if (data.m_type == eVCNone)
        return;
    stream >> value;
    data.m_bAllowNormalVictory = value != 0;
    stream >> value;
    data.m_bAppliesToComputer = value != 0;
    switch (data.m_type) {
    case eVCAquireArtifact:
        if (version >= 21) {
            short artifact;
            stream >> artifact;
            data.m_aquireArtifact.m_artifact = TArtifact(artifact);
        } else {
            signed char artifact;
            stream >> artifact;
            data.m_aquireArtifact.m_artifact = TArtifact(artifact);
        }
        break;
    case eVCAccumulateCreature:
        {
            if (version >= 20) {
                short creatureType;
                stream >> creatureType;
                data.m_accumulateCreature.m_creatureType = TCreatureType(creatureType);
            } else {
                unsigned char creatureType;
                stream >> creatureType;
                data.m_accumulateCreature.m_creatureType = TCreatureType(creatureType);
                if (creatureType == 0xff)
                    data.m_accumulateCreature.m_creatureType = TCreatureType(-1);
            }
            long quantity;
            stream >> quantity;
            data.m_accumulateCreature.m_quantity = quantity;
        }
        break;
    case eVCAccumulateResource:
        {
            signed char resourceType;
            stream >> resourceType;
            data.m_accumulateResource.m_resourceType = TGameResourceType(resourceType);
            long quantity;
            stream >> quantity;
            data.m_accumulateResource.m_quantity = quantity;
        }
        break;
    case eVCUpgradeTown:
        {
            stream >> data.m_upgradeTown.m_townLoc;
            signed char hallLevel;
            stream >> hallLevel;
            data.m_upgradeTown.m_hallLevel = hallLevel;
            signed char castleLevel;
            stream >> castleLevel;
            data.m_upgradeTown.m_castleLevel = castleLevel;
        }
        break;
    case eVCBuildHolyGrailStruct:
        stream >> data.m_buildHolyGrailStruct.m_townLoc;
        break;
    case eVCDefeatHero:
        stream >> data.m_defeatHero.m_heroLoc;
        break;
    case eVCCaptureTown:
        stream >> data.m_captureTown.m_townLoc;
        break;
    case eVCDefeatMonster:
        stream >> data.m_defeatMonster.m_monsterLoc;
        break;
    case eVCTransportArtifact:
        {
            unsigned char artifact;
            stream >> artifact;
            data.m_transportArtifact.m_artifact = TArtifact(artifact);
            stream >> data.m_transportArtifact.m_townLoc;
        }
        break;
    }
}

VA(0x00422ad0, 0x98)
void TGameMapHeader::_readLossCondition(TLossConditionData& data, TRawIStream& stream, int version)
{
    signed char type;
    stream >> type;
    data.m_type = type;
    switch (data.m_type) {
    case eLCLoseTown:
        stream >> data.m_loseTown.m_townLoc;
        break;
    case eLCLoseHero:
        stream >> data.m_loseHero.m_heroLoc;
        break;
    case eLCTimeExpires:
        {
            short numDays;
            stream >> numDays;
            data.m_timeExpires.m_numDays = numDays;
        }
        break;
    }
}

VA(0x00422b70, 0xd4a)
TGameMapHeader::TGameMapHeader(TRawIStream& stream, int version)
{
    if (version >= 10) {
        signed char bPlayable;
        stream >> bPlayable;
        m_bPlayable = bPlayable != 0;
    } else {
        m_bPlayable = true;
    }
    long dimension;
    stream >> dimension;
    m_dimension = dimension;
    signed char bTwoLayer;
    stream >> bTwoLayer;
    m_bTwoLayer = bTwoLayer != 0;
    stream >> m_name >> m_desc;
    signed char difficulty;
    stream >> difficulty;
    m_difficulty = difficulty;
    if (version >= 20) {
        unsigned char maxHeroLevel;
        stream >> maxHeroLevel;
        m_maxHeroLevel = maxHeroLevel;
    } else {
        m_maxHeroLevel = 0;
    }
    for (unsigned int player = 0; player < kNumPlayers; player++) {
        TPlayerSlot& slot = m_aPlayer[player];
        signed char bHumanPlayable;
        stream >> bHumanPlayable;
        slot.m_bHumanPlayable = bHumanPlayable != 0;
        signed char bComputerPlayable;
        stream >> bComputerPlayable;
        slot.m_bComputerPlayable = bComputerPlayable != 0;
        signed char behaviorType;
        stream >> behaviorType;
        slot.m_behaviorType = TPlayerInfo::TBehaviorType(behaviorType);
        if (version >= 8) {
            if (version >= 26) {
                signed char bCustomTownTypes;
                stream >> bCustomTownTypes;
                slot.m_bCustomTownTypes = bCustomTownTypes != 0;
            }
            if (version >= 16) {
                readBitset(stream, slot.m_townTypes);
            } else {
                std::bitset<8> townTypes;
                readBitset(stream, townTypes);
                std::copy(TBitsetIterator<8>(townTypes, 0), TBitsetIterator<8>(townTypes, 8),
                          TBitsetIterator<kNumTownTypes>(slot.m_townTypes, 0));
            }
            signed char bRandomTown;
            stream >> bRandomTown;
            slot.m_bRandomTown = bRandomTown != 0;
        }
        if (version >= 9) {
            signed char bHasMainTown;
            stream >> bHasMainTown;
            slot.m_bHasMainTown = bHasMainTown != 0;
            if (slot.m_bHasMainTown) {
                if (version >= 17) {
                    signed char bGenerateHero;
                    stream >> bGenerateHero;
                    slot.m_bGenerateHero = bGenerateHero != 0;
                    signed char mainTownType;
                    stream >> mainTownType;
                    slot.m_mainTownType = mainTownType;
                    stream >> slot.m_mainTownLoc;
                } else {
                    slot.m_bGenerateHero = true;
                    slot.m_mainTownType = -1;
                    stream >> slot.m_mainTownLoc;
                }
            } else {
                slot.m_bGenerateHero = false;
            }
        }
        if (version >= 13) {
            signed char bRandomHero;
            stream >> bRandomHero;
            slot.m_bRandomHero = bRandomHero != 0;
            unsigned char heroID;
            stream >> heroID;
            slot.m_heroID = heroID;
            if (heroID != 0xff) {
                unsigned char heroPortrait;
                stream >> heroPortrait;
                slot.m_heroPortrait = heroPortrait;
                stream >> slot.m_heroName;
            }
        }
        if (version >= 17) {
            signed char numPlaceholders;
            stream >> numPlaceholders;
            slot.m_numPlaceholders = numPlaceholders;
        } else {
            slot.m_numPlaceholders = 0;
        }
        if (version >= 18) {
            unsigned int numHeroes;
            stream >> numHeroes;
            slot.m_heroes.resize(numHeroes, THeroIdentity());
            for (unsigned int i = 0; i < numHeroes; i++) {
                unsigned char heroID;
                stream >> heroID;
                slot.m_heroes[i].m_heroID = heroID;
                stream >> slot.m_heroes[i].m_name;
            }
        }
    }
    if (version < 9) {
        char unused;
        stream.read(&unused, sizeof(unused));
    }
    _readVictoryCondition(m_vcData, stream, version);
    _readLossCondition(m_lcData, stream, version);
    signed char numTeams;
    stream >> numTeams;
    m_numTeams = numTeams;
    if (m_numTeams > 0) {
        for (unsigned int player = 0; player < kNumPlayers; player++) {
            signed char team;
            stream >> team;
            m_aTeam[player] = team;
        }
    } else {
        std::fill_n(m_aTeam, static_cast<unsigned int>(kNumPlayers), 0);
    }
    if (version >= 16) {
        readBitset(stream, m_availableHeroes);
    } else if (version >= 8) {
        std::bitset<128> availableHeroes;
        readBitset(stream, availableHeroes);
        std::copy(TBitsetIterator<128>(availableHeroes, 0), TBitsetIterator<128>(availableHeroes, 128),
                  TBitsetIterator<kNumHeroes>(m_availableHeroes, 0));
    }
    if (version >= 17) {
        unsigned int numPlaceholderHeroes;
        stream >> numPlaceholderHeroes;
        m_placeholderHeroIDs.reserve(numPlaceholderHeroes);
        for (unsigned int i = 0; i < numPlaceholderHeroes; i++) {
            unsigned char heroID;
            stream >> heroID;
            m_placeholderHeroIDs.push_back(heroID);
        }
    }
    if (version >= 25) {
        unsigned char numCustomHeroes;
        stream >> numCustomHeroes;
        for (unsigned int i = 0; i < numCustomHeroes; i++) {
            std::string name;
            TPlayerMask availability;
            unsigned char heroID;
            stream >> heroID;
            unsigned char portrait;
            stream >> portrait;
            int portraitID = portrait;
            if (portraitID == 0xff)
                portraitID = -1;
            stream >> name;
            if (version >= 26)
                readBitset(stream, availability);
            else
                availability = ~TPlayerMask();
            m_customHeroes.insert(std::map<int, TCustomHero>::value_type(
                heroID, TCustomHero(portraitID, name, availability)));
        }
    }
}
