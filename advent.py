#!/usr/bin/env python

'''
I converted adventure from Fortran IV to python as directly as possible.
Python has no GOTOs and adventure felt like it was made of nothing but a
maze of twisty little GOTOs!  When multiple GOTOs went to the same
line number I created a subroutine.  The resulting call tree results in
unintended recursion, so you will notice that many subroutines return a
small dictionary of a subroutine name and its arguments.  The dictionary
is created at the bottommost level in the call sequence and bubbled up
to the very top so that recursion can be avoided.  There is probably a
better solution.

The many, many globals have been collected into dictionaries.  This has
two advantages.  One, is that is simpler to pass a global dictionary than
the individual variables, but it also makes suspend/resume possible since
the dictionary reflects game state.  And besides, the original suspend
method of having the player save the core image image is more than a small
challenge today!

The original code was written on a machine with 5 bytes per word, and
remnants of that are still seen in the code with 5 character strings.  Bit
operations on 5-byte integers which are also 5-char strings cannot be
converted directly.  I didn't convert the XORing of strings to hide them and
prevent scanning the running program since the python source has it all it
plaintext.  I similarly bypassed the password challenge to prove a player is
a wizard.  It is almost certainly running on a machine controlled by the
player.  For old times' sake, you still must provide the password.

Original comments are maintained but I've added more during the course of
reverse engineering the logic in order to port the code.  As time allows I
hope to improve the ported code and bring it up to modern standards.  But
don't hold your breath. :-)

Mike Markowski, mike.ab3ap@gmail.com
Oct 2024
'''

from numpy.random import random, randint
import datetime, time
import os, sys

#  Adventures

#  Current limits:
#   9650 words of message text (lines, linsiz).
#    750 travel options (travel, trvsiz).
#    300 vocabulary words (ktab, atab, tabsiz).
#    150 locations (ltext, stext, key, cond, abb, atloc, locsiz).
#    100 objects (plac, place, fixd, fixed, link (twice), ptext, prop).
#     35 "action" verbs (actspk, vrbsiz).
#    205 random messages (rtext, rtxsiz).
#     12 different player classifications (ctext, cval, clsmax).
#     20 hints, less 3 (hintlc, hinted, hints, hntsiz).
#     35 magic messages (mtext, magsiz).
# There are also limits which cannot be exceeded due to the structure of
# the database.  (E.g., the vocabulary uses n/1000 to determine word type,
# so there can't be more than 1000 words.)  These upper limits are:
#   1000 non-synonymous vocabulary words
#    300 locations
#    100 objects

# Statement Functions
#
#
# toting(obj)  =  True if the obj is being carried
# here(obj)    =  True if the obj is at "loc" (or is being carried)
# at(obj)      =  True if on either side of two-placed object
# liq(dummy)   =  Object number of liquid in bottle
# liqloc(loc)  =  Object number of liquid (if any) at loc
# bitset(l,n)  =  True if cond[l] has bit n set (bit 0 is units bit)
# forced(loc)  =  True if loc moves without asking for input (cond = 2)
# dark(dummy)  =  True if location "loc" is dark
# pct(n)       =  True n% of the time (n integer from 0 to 100)
#
# wzdark says whether the loc he's leaving was dark
# lmwarn says whether he's been warned about lamp going dim
# closng says whether its closing time yet
# panic says whether he's found out he's trapped in the cave
# closed says whether we're all the way closed
# gaveup says whether he exited via "quit"
# scorng indicates to the score routine whether we're doing a "score" command
# demo is true if this is a prime-time demonstration game
# yea is random yes/no reply

wizcom = {}

toting = lambda obj: g['place'][obj] == -1
here   = lambda obj: g['place'][obj] in [-1, g['loc']]
at     = lambda obj: g['loc'] in [g['place'][obj], g['fixed'][obj]]
bitset = lambda loc,n: (g['cond'][loc] & (1<<n)) != 0
forced = lambda loc: g['cond'][loc] == 2 # Forced motion at loc.
pct    = lambda n: 100*random() < n

def dark():
    if g['cond'][g['loc']] & 1: # Light bit set, not dark.
        return False
    if not here(w['lamp']): # No lamp here, must be dark.
        return True
    return g['prop'][w['lamp']] == 0 # Light/dark when lamp on/off.

def liq():
    '''What's in the bottle.'''

    c = g['prop'][w['bottle']]
    match max(c, -1-c):
        case 0: return w['water']
        case 1: return 0
        case 2: return w['oil']

def liqloc(loc): # Liquid at this location.
    c = g['cond'][loc]
    if   c & 0b100 == 0: return 0 # No liquid.
    elif c & 0b010 == 0: return w['water']
    else:                return w['oil']

def main():
    global g

    g = globalsInit() # The many, many globals of adventure.
    dbRead()
    adventures()

def adventures():
    # Start-up, dwarf stuff

    global c, g, w, wizcom

    d = {} # Dictionary of return values during turn-taking.
    c['demo'] = start()
    motd(False)
    random()
    tk = 20*[0] # Used with dwarves later.
    g['hinted'][3] = yes(65,1,0) # WELCOME TO ADVENTURE!!  INSTRUCTIONS?

    g['newloc'] = 1
    g['loc'] = 1 # END OF A ROAD BEFORE A SMALL BRICK BUILDING.
    g['setup'] = 3
    g['limit'] = 330 # Lifetime of lamp in turns.
    if g['hinted'][3]:
        g['limit'] = 1000 # Extra lamp time if instructions requested.

    while True:
        if d != {}:
            match d['fn']:
                case None:
                    pass
                case 'newLocation':
                    d = newLocation(d['goto'], d['verb'], d['kk'])
                    continue
                case 'newTurn':
                    d = newTurn(0, d['spk'])
                    continue
        # Line 2
        # Can't leave cave once it's closing (except by Main Office).
        if (0 < g['newloc'] < 9) and c['closng']:
            rspeak(130) # EXIT CLOSED. LEAVE VIA OFFICE.
            g['newloc'] = g['loc']
            if not c['panic']:
                c['clock2'] = 15 # Give him 15 turns to leave.
            c['panic'] = True

        # See if a dwarf has seen him and has come from where he wants to go.
        # If so, the dwarf's blocking his way.  If coming from place forbidden
        # to pirate (dwarves rooted in place) let him get out (and attacked).
        if not (g['newloc'] == g['loc'] or forced(g['loc'])
            or bitset(g['loc'],3)):
            for i in range(1, 5+1):
                if g['odloc'][i] != g['newloc'] or not g['dseen'][i]:
                    continue
                g['newloc'] = g['loc']
                rspeak(2) # A LITTLE DWARF WITH A BIG KNIFE BLOCKS YOUR WAY.
                break
        g['loc'] = g['newloc']

        # Dwarf stuff.  See earlier comments for description of variables.
        # Remember sixth dwarf is pirate and is thus very different except for
        # motion rules.

        # First off, don't let the dwarves follow him into a pit or a wall.
        # Activate the whole mess the first time he gets as far as the Hall of
        # Mists (loc 15).  If newloc is forbidden to pirate (in particular, if
        # it's beyond the troll bridge), bypass dwarf stuff.  That way pirate
        # can't steal return toll, and dwarves can't meet the bear.  Also means
        # dwarves won't follow him into dead end in maze, but c'est la vie.
        # They'll wait for him outside the dead end.
        if g['loc'] == 0 or forced(g['loc']) or bitset(g['newloc'],3):
            d = location()
            continue

        if c['dflag'] == 0:
            if g['loc'] >= 15: # In or beyond Hall of Mists.
                c['dflag'] = 1 # Activate dwarves.
            d = location()
            continue

        # When we encounter the first dwarf, we kill 0, 1, or 2 of the 5
        # dwarves.  If any of the survivors is at loc, replace him with the
        # alternate.
        if c['dflag'] == 1:
            if g['loc'] < 15 or pct(95): # 5% of time, dwarf follows.
                d = location()
                continue
            c['dflag'] = 2 # Indicate that dwarf is following.
            for _ in range(1,2+1): # Kill up to 2 dwarves.
                j = 1 + randint(5)
                # If saved not = -1, he bypassed the "start" call.
                if pct(50) and c['saved'] == -1:
                    g['dloc'][j] = 0 # Kill dwarf.
            for i in range(1, 5+1):
                if g['dloc'][i] == g['loc']: # Surviving dwarf here.
                    g['dloc'][i] = g['daltlc'] # Alternate from Nugget Rm.
                g['odloc'][i] = g['dloc'][i] # Move dwarf here.
            rspeak(3) # DWARF THREW AXE AT YOU AND MISSED.
            drop(w['axe'], g['loc'])
            d = location()
            continue

        # Things are in full swing.  Move each dwarf at random, except if
        # he's seen us he sticks with us.  Dwarves never go to locs <15.  If
        # wandering at random, they don't back up unless there's no
        # alternative.  If they don't have to move, they attack.  And, of
        # course, dead dwarves don't do much of anything.
        dtotal = 0
        attack = 0
        stick = 0
        for i in range(1, 6+1): # Loop through all dwarves.
            if g['dloc'][i] == 0: # Dead dwarf.
                continue
            j = 1
            kk = g['dloc'][i] # Location of living dwarf.
            kk = g['key'][kk] # travel[key[n]] first newloc from loc n
            if kk != 0:
                while True:
                    g['newloc'] = abs(g['travel'][kk])//1000%1000
                    if not (g['newloc'] < 15 # Before Hall of Mists
                        or g['newloc'] > 300 # Off map.
                        or g['newloc'] == g['odloc'][i] # Dwarf's old loc.
                        or (j > 1 and g['newloc'] == tk[j-1])
                        or j >= 20 # Beyond end of tk[].
                        or g['newloc'] == g['dloc'][i]
                        or forced(g['newloc'])
                        or (i == 6 and bitset(g['newloc'],3))
                        or abs(g['travel'][kk])//1000000 == 100):
                        tk[j] = g['newloc']
                        j += 1
                    kk += 1 # Look at next potential newloc.
                    if g['travel'][kk-1] < 0: # Last possible newloc.
                        break
            tk[j] = g['odloc'][i]
            if j >= 2:
                j -= 1
            j = 1 + randint(j)
            g['odloc'][i] = g['dloc'][i]
            g['dloc'][i] = tk[j]
            g['dseen'][i] = (
                (g['dseen'][i] and g['loc'] >= 15) # Seen and >= Hall of Mists.
                or g['dloc'][i] == g['loc']        # Dwarf is here.
                or g['odloc'][i] == g['loc'])      # Dwarf was just here.
            if not g['dseen'][i]: # Not seen by dwarf.
                continue
            g['dloc'][i] = g['loc']
            if i == 6: # == pirate.
                # The pirate's spotted him.  He leaves him alone once we've
                # found chest.  K counts if a treasure is here.  If not, and
                # tally = tally2 plus one for an unseen chest, let the pirate
                # be spotted.  Use place[messag] to determine if pirate's
                # been seen, since place[chest] = 0 could mean he threw it to
                # troll.
                if g['loc'] == g['chloc'] or g['prop'][w['chest']] >= 0:
                    continue
                k = 0
                for j in range(50, g['maxtrs']+1): # Treasures are >= 50.
                    # Pirate won't take pyramid from Plover Room or Dark Room
                    # (too easy!).
                    if (j != w['pyram'] or not g['loc']
                        in [g['plac'][w['pyram']], g['plac'][w['emrald']]]):
                        if toting(j): # Non-pyramid, non-emerald here.
                            break
                    if here(j):
                        k = 1
                else:
                    if (g['tally'] == g['tally2']+1      # Unseen chest.
                        and k == 0                       # No treasure here.
                        and g['place'][w['messag']] == 0
                        and here(w['lamp'])              # Lamp is here
                        and g['prop'][w['lamp']] == 1):  # and is on.
                        rspeak(186) # FAINT RUSTLING NOISES...
                        move(w['chest'], g['chloc'])
                        move(w['messag'], g['chloc2'])
                        g['dloc'][6] = g['chloc']
                        g['odloc'][6] = g['chloc']
                        g['dseen'][6] = False
                        continue
                    if g['odloc'][6] != g['dloc'][6] and pct(20):
                        rspeak(127) # FAINT RUSTLING NOISES...
                    continue

                rspeak(128) # A BEARDED PIRATE!
                if g['place'][w['messag']] == 0:
                    move(w['chest'],g['chloc'])
                move(w['messag'],g['chloc2'])
                for j in range(50, g['maxtrs']):
                    if (j == w['pyram'] and (g['loc']
                        in [g['plac'][w['pyram']], g['plac'][w['emrald']]])):
                        continue
                    if at(j) and g['fixed'][j] == 0:
                        carry(j,g['loc'])
                    if toting(j):
                        drop(j,g['chloc'])
                g['dloc'][6] = g['chloc']
                g['odloc'][6] = g['chloc']
                g['dseen'][6] = False
                continue

            # This threatening little dwarf is in the room with him!
            dtotal += 1
            if g['odloc'][i] != g['dloc'][i]:
                continue
            attack += 1
            if g['knfloc'] >= 0:
                g['knfloc'] = g['loc'] # Put knife here.
            if 1000*random() < 95*(c['dflag']-2):
                stick += 1

        # Now we know what's happening.  Let's tell the poor sucker about it.
        if dtotal == 0: # Dwarf total is zero.
            d = location()
            continue
        if dtotal != 1:
            s = '\n THERE ARE %d THREATENING LITTLE DWARVES IN THE ROOM WITH '
            s += 'YOU.'
            print(s % dtotal)
        else:
            rspeak(4) # THREATENING LITTLE DWARF
        if attack == 0:
            d = location()
            continue
        if c['dflag'] == 2:
            c['dflag'] = 3
        # If saved not = -1, he bypassed the "start" call.  Dwarves get
        # *very* mad!
        if c['saved'] != -1:
            c['dflag'] = 20
        if attack == 1:
            rspeak(5) #  KNIFE IS THROWN AT YOU!
            k = 52
        else:
            print('\n %d OF THEM THROW KNIVES AT YOU!' % attack)
            k = 6
        if stick <= 1:
            rspeak(k+stick)
            if stick == 0:
                d = location()
                continue
        else:
            print('\n %d OF THEM GET YOU!' % stick)
        g['oldlc2'] = g['loc']
        d = dead(pit=False)

def analyseObject(obj, verb=0):
    '''
    Analyse an object word.  See if the thing is here, whether we've got a
    verb yet, and so on.  Object must be here unless verb is "find" or
    "invent(ory)" (and no new verb yet to be analysed).  Water and oil are
    also funny, since they are never actually dropped at any location, but
    might be here inside the bottle or as a feature of the location.
    '''

    global g

    g['obj'] = obj # For use in transitive().
    skip = g['fixed'][obj] != g['loc'] and not here(obj)
    while True:
        if not skip:
            if g['wd2'] != '': # Line 5010
                return secondWord()
            if g['verb'] != 0:
                spk = g['actspk'][g['verb']] # Default message for verb.
                return transitive(spk)
            tk = g['wd1'].strip() + g['wd1x'].strip() + '?'
            print('\n WHAT DO YOU WANT TO DO WITH THE %s' % tk)
            return {'fn':'newTurn', 'spk':-1}
        skip = False
        if obj == w['grate']: # Line 5100
            if g['loc'] in [1,4,7]: # End of road, valley or streambed slit.
                obj = w['dprssn']
            if 9 < g['loc'] < 15: # In cave, haven't reached Hall of Mists.
                obj = w['entrnc']
            if obj != w['grate']:
                return {'fn':'newLocation','goto':8, 'verb':obj, 'kk':-1}
        if obj == w['dwarf']:
            upTop = False
            for i in range(1, 5+1):
                if g['dloc'][i] == g['loc'] and c['dflag'] >= 2:
                    upTop = True
            if upTop:
                continue
        if (liq() == obj and here(w['bottle'])) or obj == liqloc(g['loc']):
            continue
        if (g['obj'] == w['plant'] and at(w['plant2'])
            and g['prop'][w['plant2']] != 0):
            g['obj'] = w['plant2']
            continue
        if g['obj'] == w['knife'] and g['knfloc'] == g['loc']:
            g['knfloc'] = -1
            spk = 116 # DWARVES' KNIVES VANISH AS THEY STRIKE WALLS OF THE CAVE.
            return {'fn':'newTurn', 'spk':spk}
        if g['obj'] == w['rod'] and here(w['rod2']):
            g['obj'] = w['rod2']
            continue
        if (g['verb'] in [w['find'], w['invent']]) and g['wd2'] == '':
            continue
        break
    tk = g['wd1'].strip() + g['wd1x'].strip() + ' HERE.'
    print('\n I SEE NO %s' % tk)
    return {'fn':'newTurn', 'spk':0}

def analyseVerb(verb):
    # Analyse a verb.  Remember what it was, go back for object if second word
    # unless verb is "say", which snarfs arbitrary second word.

    g['verb'] = verb
    if g['wd2'] != '' and verb != w['say']:
        return secondWord()
    if verb == w['say']:
        if g['wd2'] == '':
            g['obj'] = 0
        else:
            g['obj'] = vocab(g['wd2'],-1)
    spk = g['actspk'][verb] # Default message for verb.
    if g['obj'] == 0:
        return intransitive(spk)
    else:
        return transitive(spk)

def analyseWord():
    global wd1, wd1x

    i = vocab(g['wd1'], -1)
    if i == -1:
        # Gee, i don't understand.
        tk = g['wd1'].strip() + g['wd1x'].strip() + '".'
        print('\n SORRY, I DON\'T KNOW THE WORD "%s' % tk)
        return {'fn':'newTurn', 'spk':-1}
    wType,wNum = divmod(i, 1000)

    '''
    Section 4: Vocabulary.  Each line contains a number (n), a tab, and a
       five-letter word.  Call m = n/1000.  If m = 0, then the word is a motion
       verb for use in travelling (see section 3).  Else, if m = 1, the word is
       an object.  Else, if m = 2, the word is an action verb (such as "carry"
       or "attack").  Else, if m = 3, the word is a special case verb (such as
       "dig") and n mod 1000 is an index into section 6.  Objects from 50 to
       (currently, anyway) 79 are considered treasures (for pirate, closeout).
    '''

    match wType:
        case 0: # Motion verb.
            return newLocation(8, wNum) # goto 2 or newLoc.
        case 1: # Object.
            return analyseObject(wNum) # newTurn or newLoc.
        case 2: # Action verb.
            return analyseVerb(wNum) # trans() or intrans()
        case 3: # Special verb like "DIG".
            return {'fn':'newTurn', 'spk':wNum}
        case _:
            bug(22) # Vocabulary type (n/1000) not between 0 and 3.

def attack(spk):
    # ATTACK.  Assume target if unambiguous.  "Throw" also links here.
    # Attackable objects fall into two categories: enemies (snake, dwarf,
    # etc.) and others (bird, clam).  Ambiguous if two enemies, or if no
    # enemies but two others.
    #
    # Verb can be ATTAC,KILL,FIGHT,HIT,STRIK,SLAY.

    global c, g, w

    for i in range(1, 5+1):
        if g['dloc'][i] == g['loc'] and c['dflag'] >= 2:
            break # Dwarf here and following player.
    else:
        i = 0
    if g['obj'] == 0: # Intransitive, find object.
        if i != 0: # Which following dwarf is present.
            g['obj'] = w['dwarf']
        if here(w['snake']):
            g['obj'] = g['obj']*100 + w['snake']
        if at(w['dragon']) and g['prop'][w['dragon']] == 0:
            g['obj'] = g['obj']*100 + w['dragon']
        if at(w['troll']):
            g['obj'] = g['obj']*100 + w['troll']
        if here(w['bear']) and g['prop'][w['bear']] == 0:
            g['obj'] = g['obj']*100 + w['bear']
        if g['obj'] > 100: # Multiple potential objects here.
            return what() # Ask, ATTACK WHAT?
        if g['obj'] == 0: # Still looking for object.
            # Can't attack bird by throwing axe.
            if here(w['bird']) and g['verb'] != w['throw']:
                g['obj'] = w['bird']
            # Clam and oyster both treated as clam for intransitive case; no
            # harm done.
            if here(w['clam']) or here(w['oyster']):
                g['obj'] = 100*g['obj'] + w['clam']
            if g['obj'] > 100: # Multiple potential objects here.
                return what()
    if g['obj'] == w['bird']:
        spk = 137 # OH, LEAVE THE POOR UNHAPPY BIRD ALONE.
        if c['closed']:
            return {'fn':'newTurn', 'spk':spk}
        dstroy(w['bird'])
        g['prop'][w['bird']] = 0 # Dead bird.
        if g['place'][w['snake']] == g['plac'][w['snake']]: # At initial loc.
            g['tally2'] += 1 # Cannot find bird again.
        spk = 45 # THE LITTLE BIRD IS NOW DEAD.
    if g['obj'] == 0: # Never found an object.
        spk = 44 # THERE IS NOTHING HERE TO ATTACK.
    if g['obj'] in [w['clam'], w['oyster']]:
        spk = 150 # THE SHELL IS VERY STRONG
    if g['obj'] == w['snake']:
        spk = 46 # ATTACKING THE SNAKE DOESN'T WORK.
    if g['obj'] == w['dwarf']:
        spk = 49 # WITH WHAT?  YOUR BARE HANDS?
    if g['obj'] == w['dwarf'] and c['closed']:
        dwarvesDisturbed() # Game ends.
    if g['obj'] == w['dragon']:
        spk = 167 # THE POOR THING IS ALREADY DEAD!
    if g['obj'] == w['troll']:
        spk = 157 # TROLLS ARE CLOSE RELATIVES WITH THE ROCKS...
    if g['obj'] == w['bear']:
        spk = 165 + (g['prop'][w['bear']] + 1)//2
    if g['obj'] != w['dragon'] or g['prop'][w['dragon']] != 0:
        return {'fn':'newTurn', 'spk':spk}
    # Fun stuff for dragon.  If he insists on attacking it, win!  Set prop to
    # dead, move dragon to central loc (still fixed), move rug there (not
    # fixed), and move him there, too.  Then do a null motion to get new
    # description.
    rspeak(49) # WITH WHAT?  YOUR BARE HANDS?
    g['verb'] = 0
    g['obj'] = 0
    g['wd1'],g['wd1x'],g['wd2'],g['wd2x'] = getin()
    if g['wd1'] not in ['Y', 'YES']:
        return foobarEtc(g['verb'])
    pspeak(w['dragon'],1) # YOU HAVE JUST VANQUISHED A DRAGON
    g['prop'][w['dragon']] = 2 # Dead.
    g['prop'][w['rug']] = 0 # Put rug here.
    k = (g['plac'][w['dragon']] + g['fixd'][w['dragon']])//2
    move(w['dragon'] + 100, -1)
    move(w['rug'] + 100, 0)
    move(w['dragon'], k)
    move(w['rug'], k)
    for obj in range(1, 100+1):
        if (g['place'][obj] == g['plac'][w['dragon']]
            or g['place'][obj] == g['fixd'][w['dragon']]):
            move(obj, k)
    g['loc'] = k
    k = w['null']
    return {'fn':'newLocation', 'goto':8, 'verb':k, 'kk':-1}

def badMotion(k):
    #  Non-applicable motion.  Various messages depending on word given.

    spk = 12 # I DON'T KNOW HOW TO APPLY THAT WORD HERE.
    if 43 <= k <= 50:
        spk = 9 # THERE IS NO WAY TO GO THAT DIRECTION.
    if k in [29, 30]:
        spk = 9
    if k in [7, 36, 37]:
        spk = 10 # USE COMPASS POINTS OR NEARBY OBJECTS.
    if k in [11, 19]:
        spk = 11 # USE COMPASS POINTS OR NAME SOMETHING IN GENERAL DIRECTION
#   if verb in [w['find'], w['invent']]: # XXX BUG??? verb, not k.
    if k in [w['find'], w['invent']]:
        spk = 59 # I CANNOT TELL YOU WHERE REMOTE THINGS ARE.
    if k in [62, 65]:
        spk = 42 # NOTHING HAPPENS.
    if k == 17:
        spk = 80 # WHICH WAY?
    rspeak(spk)
    return {'fn':None} # goto 2

def blast(spk):
    # BLAST.  No effect unless you've got dynamite, which is a neat trick!

    if g['prop'][w['rod2']] < 0 or not c['closed']:
        return {'fn':'newTurn', 'spk':spk}
    c['bonus'] = 133 # LOUD EXPLOSION...BURYING THE DWARVES
    if g['loc'] == 115: # NE storage room.
        c['bonus'] = 134 # LOUD EXPLOSION...BURYING THE SNAKES
    if here(w['rod2']):
        c['bonus'] = 135 # LOUD EXPLOSION...YOU ARE SPLASHED ACROSS WALLS
    rspeak(c['bonus'])
    finish()

def breakObj(spk):
    #  BREAK.  Only works for mirror in repository and, of course, the vase.

    global g

    if g['obj'] == w['mirror']:
        spk = 148 # TOO FAR UP FOR YOU TO REACH.
    if not (g['obj'] == w['vase'] and g['prop'][w['vase']] == 0):
        if g['obj'] != w['mirror'] or not c['closed']:
            return {'fn':'newTurn', 'spk':spk}
        rspeak(197) # MIRROR IT SHATTERS INTO A MYRIAD TINY FRAGMENTS.
        dwarvesDisturbed()
    spk = 198 # VASE HURLED DELICATELY TO THE GROUND.
    if toting(w['vase']):
        drop(w['vase'], g['loc'])
    g['prop'][w['vase']] = 2 # Shattered.
    g['fixed'][w['vase']] = -1 # Gone.
    return {'fn':'newTurn', 'spk':spk}

def brief():
    # BRIEF.  Intransitive only.  Suppress long descriptions after first
    # time.

    global c

    spk = 156 # I'LL ONLY DESCRIBE A PLACE IN FULL THE FIRST TIME
    c['abbnum'] = 10000
    c['detail'] = 3
    return {'fn':'newTurn', 'spk':spk}

def bug(num):
    '''
    The following conditions are currently considered fatal bugs.  Numbers < 20
    are detected while reading the database; the others occur at "run time".
      0   Message line > 70 characters
      1   Null line in message
      2   Too many words of messages
      3   Too many travel options
      4   Too many vocabulary words
      5   Required vocabulary word not found
      6   Too many rtext or mtext messages
      7   Too many hints
      8   Location has cond bit being set twice
      9   Invalid section number in database
      20  Special travel (500>l>300) exceeds goto list
      21  Ran off end of vocabulary table
      22  Vocabulary type (n/1000) not between 0 and 3
      23  Intransitive action verb exceeds goto list
      24  Transitive action verb exceeds goto list
      25  Conditional travel entry with no alternative
      26  Location has no travel entries
      27  Hint number exceeds goto list
      28  Invalid month returned by date function
    '''

    print(' FATAL ERROR, SEE SOURCE CODE FOR INTERPRETATION.')
    print(' PROBABLE CAUSE: ERRONEOUS INFO IN DATABASE.')
    print(' ERROR CODE =%2d\n' % num)
    sys.exit(0)

def carry(obj, where):
    '''
    Start toting an object, removing it from the list of things at its former
    location.  Incr holdng unless it was already being toted.  If obj>100
    (moving "fixed" second loc), don't change place or holdng.
    '''

    global g

    if obj <= 100:
        if g['place'][obj] == -1:
            return
        g['place'][obj] = -1
        c['holdng'] += 1
    if g['atloc'][where] == obj:
        g['atloc'][where] = g['link'][obj]
        return
    temp = g['atloc'][where]
    while True:
        if g['link'][temp] == obj:
            break
        temp = g['link'][temp]
    g['link'][temp] = g['link'][obj]

def caveMsg():
    # CAVE.  Different messages depending on whether above ground.
    if g['loc'] < 8:
        rspeak(57) # I DON'T KNOW WHERE THE CAVE IS, TRY THE STREAM.
    if g['loc'] >= 8:
        rspeak(58) # I NEED MORE DETAILED INSTRUCTIONS TO DO THAT.
    return {'fn':None} # goto 2

def ciao():
    '''
    Exits, after issuing reminder to save new core image.  Used when
    suspending and when creating new version via magic mode.  On some
    systems, the core image is lost once the program exits.  If so, set k=31
    instead of 32.

    --
    The above is of course no longer applicable, but let's print it for old
    times' sake. (mm, Oct 2024)
    '''
    k = 32
    mspeak(k) # BE SURE TO SAVE YOUR CORE-IMAGE...
    if k == 31:
        a,b,c,d = getin()
    sys.exit(0)

#
#   C a v e   C l o s i n g   a n d   S c o r i n g
#
#   closeClock1 & closeClock2

    '''
    These sections handle the closing of the cave.  The cave closes "clock1"
    turns after the last treasure has been located (including the pirate's
    chest, which may of course never show up).  Note that the treasures need
    not have been taken yet, just located.  Hence clock1 must be large enough
    to get out of the cave (it only ticks while inside the cave).  When it
    hits zero, we branch to 10000 to start closing the cave, and then sit
    back and wait for him to try to get out.  If he doesn't within clock2
    turns, we close the cave; if he does try, we assume he panics, and give
    him a few additional turns to get frantic before we close.  When clock2
    hits zero, we branch to 11000 to transport him into the final puzzle.
    Note that the puzzle depends upon all sorts of random things.  For
    instance, there must be no water or oil, since there are beanstalks which
    we don't want to be able to water, since the code can't handle it.  Also,
    we can have no keys, since there is a grate (having moved the fixed
    object!) there separating him from all the treasures.  Most of these
    problems arise from the use of negative prop numbers to suppress the
    object descriptions until he's actually moved the objects.

    When the first warning comes, we lock the grate, destroy the bridge, kill
    all the dwarves (and the pirate), remove the troll and bear (unless
    dead), and set "closng" to true.  Leave the dragon; too much trouble to
    move it.  From now until clock2 runs out, he cannot unlock the grate,
    move to any location outside the cave (loc<9), or create the bridge.  Nor
    can he be resurrected if he dies.  Note that the snake is already gone,
    since he got to the treasure accessible only via the hall of the Mt.
    King.  Also, he's been in giant room (to get eggs), so we can refer to
    it.  Also also, he's gotten the pearl, so we know the bivalve is an
    oyster.  *And*, the dwarves must have been activated, since we've found
    chest.
    '''

def closeClock1():
    global g

    # Line 10000
    g['prop'][w['grate']] = 0 # Lock the grate.
    g['prop'][w['fissur']] = 0 # Destroy the bridge.
    for i in range(1, 6+1):
        g['dseen'][i] = False
        g['dloc'][i] = 0 # Kill each dwarf or pirate.
    move(w['troll'], 0) # Remove troll.
    move(w['troll']+100, 0)
    move(w['troll2'], g['plac'][w['troll']])
    move(w['troll2']+100, g['fixd'][w['troll']])
    juggle(w['chasm'])
    if g['prop'][w['bear']] != 3: # ==3, already dead.
        dstroy(w['bear']) # Remove bear.
    g['prop'][w['chain']] = 0 # Lock chain.
    g['fixed'][w['chain']] = 0
    g['prop'][w['axe']] = 0 # Take axe.
    g['fixed'][w['axe']] = 0
    rspeak(129) # "ALL ADVENTURERS EXIT IMMEDIATELY THROUGH MAIN OFFICE."
    c['clock1'] = -1
    c['closng'] = True
    return parseWords()

def closeClock2():

    '''
    Once he's panicked, and clock2 has run out, we come here to set up the
    storage room.  The room has two locs, hardwired as 115 (NE) and 116 (SW).
    At the NE end, we place empty bottles, a nursery of plants, a bed of
    oysters, a pile of lamps, rods with stars, sleeping dwarves, and him.  At
    the SW end we place grate over treasures, snake pit, covey of caged
    birds, more rods, and pillows.  A mirror stretches across one wall.  Many
    of the objects come from known locations and/or states (E.g. the snake is
    known to have been destroyed and needn't be carried away from its old
    "place"), making the various objects be handled differently.  We also
    drop all other objects he might be carrying (lest he have some which
    could cause trouble, such as the keys).  We describe the flash of light
    and trundle back.
    '''
    global g, w

    # Line 11000
    g['prop'][w['bottle']] = put(w['bottle'],115,1)
    g['prop'][w['plant']] = put(w['plant'],115,0)
    g['prop'][w['oyster']] = put(w['oyster'],115,0)
    g['prop'][w['lamp']] = put(w['lamp'],115,0)
    g['prop'][w['rod']] = put(w['rod'],115,0)
    g['prop'][w['dwarf']] = put(w['dwarf'],115,0)
    g['loc'] = 115
    g['oldloc'] = 115
    g['newloc'] = 115

    # Leave the grate with normal (non-negative) property.
    foo = put(w['grate'],116,0)
    g['prop'][w['snake']] = put(w['snake'],116,1)
    g['prop'][w['bird']] = put(w['bird'],116,1)
    g['prop'][w['cage']] = put(w['cage'],116,0)
    g['prop'][w['rod2']] = put(w['rod2'],116,0)
    g['prop'][w['pillow']] = put(w['pillow'],116,0)

    g['prop'][w['mirror']] = put(w['mirror'],115,0)
    g['fixed'][w['mirror']] = 116

    for i in range(1, 100+1):
        if toting(i):
            dstroy(i) # Remove anything he's carrying.

    rspeak(132) # BLINDING FLASH OF LIGHT...
    c['closed'] = True
    return {'fn':None} # goto 2

def closeDemo():
    # And, of course, demo games are ended by the wizard.

    global w

    # Line 13000
    mspeak(1) # SOMEWHERE NEARBY IS COLOSSAL CAVE,...
    c['gaveup'] = True
    finish()

def datime():

    '''
    Return the date and time in d and t.  d is number of days since 01-jan-77,
    t is minutes past midnight.  This is harder than it sounds, because the
    finagled dec functions return the values only as ascii strings!
    '''

    t0 = datetime.date(1977,1,1) # 1 Jan 1977 is a Saturday.
    today = datetime.date.today()
    d = (today - t0).days
    now = time.localtime()
    t = 60*now.tm_hour + now.tm_min # Minutes since midnight.
    return d, t

def dbRead():
    # Description of the database format
    #
    #
    # The data file contains several sections.  Each begins with a line
    # containing a number identifying the section, and ends with a line
    # containing "-1".
    #
    # Section 1: Long form descriptions.  Each line contains a location number,
    #    a tab, and a line of text.  The set of (necessarily adjacent) lines
    #    whose numbers are x form the long description of location x.
    # Section 2: Short form descriptions.  Same format as long form.  Not all
    #    places have short descriptions.
    # Section 3: Travel table.  Each line contains a location number (x),
    #    a second location number (y), and a list of motion numbers (see
    #    section 4).  Each motion represents a verb which will go to y if
    #    currently at x.  Y, in turn, is interpreted as follows.  Let m =
    #    y/1000, n = y mod 1000.
    #          if n<=300   it is the location to go to.
    #          if 300<n<=500     n-300 is used in a computed goto to
    #                            a section of special code.
    #          if n>500    message n-500 from section 6 is printed,
    #                            and he stays wherever he is.
    #    Meanwhile, m specifies the conditions on the motion.
    #          if m = 0            it's unconditional.
    #          if 0<m<100  it is done with m% probability.
    #          if m = 100    unconditional, but forbidden to dwarves.
    #          if 100<m<=200     he must be carrying object m-100.
    #          if 200<m<=300     must be carrying or in same room as m-200.
    #          if 300<m<=400     prop(m mod 100) must *not* be 0.
    #          if 400<m<=500     prop(m mod 100) must *not* be 1.
    #          if 500<m<=600     prop(m mod 100) must *not* be 2, etc.
    #    If the condition (if any) is not met, then the next *different*
    #    "destination" value is used (unless it fails to meet *its* conditions,
    #    in which case the next is found, etc.).  Typically, the next dest will
    #    be for one of the same verbs, so that its only use is as the alternate
    #    destination for those verbs.  For instance:
    #          15    110022      29    31    34    35    23    43
    #          15    14    29
    #    This says that, from loc 15, any of the verbs 29, 31, etc., will take
    #    him to 22 if he's carrying object 10, and otherwise will go to 14.
    #          11    303008      49
    #          11    9     50
    #    This says that, from 11, 49 takes him to 8 unless prop(3) = 0, in which
    #    case he goes to 9.  Verb 50 takes him to 9 regardless of prop(3).
    # Section 4: Vocabulary.  Each line contains a number (n), a tab, and a
    #    five-letter word.  Call m = n/1000.  If m = 0, then the word is a
    #    motion verb for use in travelling (see section 3).  Else, if m = 1,
    #    the word is an object.  Else, if m = 2, the word is an action verb
    #    (such as "carry" or "attack").  Else, if m = 3, the word is a
    #    special case verb (such as "dig") and n mod 1000 is an index into
    #    section 6.  Objects from 50 to (currently, anyway) 79 are considered
    #    treasures (for pirate, closeout).
    # Section 5: Object descriptions.  Each line contains a number (n), a tab,
    #    and a message.  If n is from 1 to 100, the message is the "inventory"
    #    message for object n.  Otherwise, n should be 000, 100, 200, etc., and
    #    the message should be the description of the preceding object when its
    #    prop value is n/100.  The n/100 is used only to distinguish multiple
    #    messages from multi-line messages; the prop info actually requires all
    #    messages for an object to be present and consecutive.  Properties which
    #    produce no message should be given the message ">$<".
    # Section 6: Arbitrary messages.  Same format as sections 1, 2, and 5,
    #    except the numbers bear no relation to anything (except for special
    #    verbs in section 4).
    # Section 7: Object locations.  Each line contains an object number and its
    #    initial location (zero (or omitted) if none).  If the object is
    #    immovable, the location is followed by a "-1".  If it has two locations
    #    (e.g. the grate) the first location is followed with the second, and
    #    the object is assumed to be immovable.
    # Section 8: Action defaults.  Each line contains an "action-verb" number
    #    and the index (in section 6) of the default message for the verb.
    # Section 9: Liquid assets, etc.  Each line contains a number (n) and up to
    #    20 location numbers.  Bit n (where 0 is the units bit) is set in
    #    cond[loc] for each loc given.  The cond bits currently assigned
    #    are:
    #          0     Light
    #          1     If bit 2 is on: on for oil, off for water
    #          2     Liquid asset, see bit 1
    #          3     Pirate doesn't go here unless following player
    #    Other bits are used to indicate areas of interest to "hint" routines:
    #          4     Trying to get into cave
    #          5     Trying to catch bird
    #          6     Trying to deal with snake
    #          7     Lost in maze
    #          8     Pondering dark room
    #          9     At Witt's End
    #    Cond[loc] is set to 2, overriding all other bits, if loc has forced
    #    motion.
    # Section 10: Class messages.  Each line contains a number (n), a tab, and a
    #    message describing a classification of player.  The scoring section
    #    selects the appropriate message, where each message is considered to
    #    apply to players whose scores are higher than the previous n but not
    #    higher than this n.  Note that these scores probably change with every
    #    modification (and particularly expansion) of the program.
    # Section 11: Hints.  Each line contains a hint number (corresponding to a
    #    cond bit, see section 9), the number of turns he must be at the right
    #    loc(s) before triggering the hint, the points deducted for taking the
    #    hint, the message number (section 6) of the question, and the message
    #    number of the hint.  These values are stashed in the "hints" array.
    #    Hntmax is set to the max hint number (<= hntsiz).  Numbers 1-3 are
    #    unusable since cond bits are otherwise assigned, so 2 is used to
    #    remember if he's read the clue in the repository, and 3 is used to
    #    remember whether he asked for instructions (gets more turns, but loses
    #    points).
    # Section 12: Magic messages. Identical to section 6 except put in a
    #    separate section for easier reference.  Magic messages are used by
    #    the startup, maintenance mode, and related routines.
    # Section 0: End of database.
    # Read the database if we have not yet done so

    global g

    if False or g['setup'] != 0: # Only for old days of computing.
        postDbInit()
    else:
        # print('INITIALISING...')
        # Clear out the various text-pointer arrays.  All text is stored in
        # array lines; each line is preceded by a word pointing to the next
        # pointer (i.e.  the word following the end of the line).  The
        # pointer is negative if this is first line of a message.  The
        # text-pointer arrays contain indices of pointer-words in lines.
        # Stext(n) is short description of location n.  Ltext(n) is long
        # description.  Ptext(n) points to message for prop(n) = 0.
        # Successive prop messages are found by chasing pointers.  Rtext
        # contains section 6's stuff.  Ctext(n) points to a player-class
        # message.  Mtext is for section 12.  We also clear cond.  See
        # description of section 9 for details.
        db = open('text', 'r')
        while True:
            # Start new data section.  Sect is the section number.
            line = db.readline().strip()
            sect = int(line)
            match sect:
                case  0: postDbInit(); break
                case  1: sections(db, 1)
                case  2: sections(db, 2)
                case  3: section3(db)
                case  4: section4(db)
                case  5: section5(db)
                case  6: sections(db, 6)
                case  7: section7(db)
                case  8: section8(db)
                case  9: section9(db)
                case 10: sections(db, 10)
                case 11: section11(db)
                case 12: sections(db, 12)
                case  _: bug(9) # Invalid section number in database.
        db.close()
        # print('INIT DONE ')

def dead(pit=True):
    '''
    "You're dead, Jim."

    If the current loc is zero, it means the clown got himself killed.  We'll
    allow this maxdie times.  Maxdie is automatically set based on the number
    of snide messages available.  Each death results in a message (81, 83,
    etc.) which offers reincarnation; if accepted, this results in message
    82, 84, etc.  The last time, if he wants another chance, he gets a snide
    remark as we exit.  When reincarnated, all objects being carried get
    dropped at oldlc2 (presumably the last place prior to being killed)
    without change of props.  The loop runs backwards to assure that the bird
    is dropped before the cage.  (This kluge could be changed once we're sure
    all references to bird and cage are done by keywords.)  The lamp is a
    special case (it wouldn't do to leave it in the cave).  It is turned off
    and left outside the building (only if he was carrying it, of course).
    He himself is left inside the building (and heaven help him if he tries
    to XYZZY back into the cave without the lamp!).  Oldloc is zapped so he
    can't just "retreat".
    '''

    # The easiest way to get killed is to fall into a pit in pitch darkness.
    if pit:
        rspeak(23) # YOU BROKE EVERY BONE IN YOUR BODY!
        g['oldlc2'] = g['loc']

    #  Okay, he's dead.  Let's get on with it.
    if c['closng']:
        # He died during closing time.  No resurrection.  Tally up a death
        # and exit.
        rspeak(131) # IT LOOKS AS THOUGH YOU'RE DEAD...CALL IT A DAY.
        c['numdie'] += 1
        finish()
    c['yea'] = yes(81+c['numdie']*2, 82+c['numdie']*2, 54) # REINCARNATE?
    c['numdie'] += 1
    if c['numdie'] == c['maxdie'] or not c['yea']:
        finish()
    g['place'][w['water']] = 0
    g['place'][w['oil']] = 0
    if toting(w['lamp']):
        g['prop'][w['lamp']] = 0
    for j in range(1, 100+1):
        i = 101 - j
        if not toting(i):
            continue
        k = g['oldlc2']
        if i == w['lamp']:
            k = 1
        drop(i, k)
    g['loc'] = 3 # Resurrected, back to the building!
    g['oldloc'] = g['loc']
    return location() # Back to top of game loop.

def discard(spk, goto9021=False):
    # Discard object.  "Throw" also comes here for most objects.  Special
    # cases for bird (might attack snake or dragon) and cage (might contain
    # bird) and vase.  Drop coins at vending machine for extra batteries.
    #
    # Also: DROP,RELEA,FREE,DISCA,DUMP.

    if not goto9021:
        # Line 9020
        if toting(w['rod2']) and g['obj'] == w['rod'] and not toting(w['rod']):
            g['obj'] = w['rod2'] # rod2 is in Storage Area, SW end.
        if not toting(g['obj']):
            return {'fn':'newTurn', 'spk':spk}
        if g['obj'] == w['bird'] and here(w['snake']):
            rspeak(30) # LITTLE BIRD ATTACKS THE GREEN SNAKE...
            if c['closed']:
                dwarvesDisturbed()
            dstroy(w['snake'])
            # Set prop for use by travel options
            g['prop'][w['snake']] = 1 # Snake run off by bird.
            skipTop = False
        else:
            skipTop = True

    while True:
        if not skipTop or goto9021:
            k = liq() # Line 9021
            if k == g['obj']:
                g['obj'] = w['bottle']
            if g['obj'] == w['bottle'] and k != 0:
                g['place'][k] = 0
            if g['obj'] == w['cage'] and g['prop'][w['bird']] != 0:
                drop(w['bird'],g['loc']) # Set bird free.
            if g['obj'] == w['bird']:
                g['prop'][w['bird']] = 0
            drop(g['obj'],g['loc'])
            return {'fn':'newTurn', 'spk':0}
        skipTop = False
        if g['obj'] == w['coins'] and here(w['vend']):
            dstroy(w['coins']) # Take his money.
            drop(w['batter'], g['loc']) # Fresh batteries for payment.
            pspeak(w['batter'], 0) # THERE ARE FRESH BATTERIES HERE.
            return {'fn':'newTurn', 'spk':0}
        elif (g['obj'] == w['bird'] and at(w['dragon'])
            and g['prop'][w['dragon']] == 0): # Bird and living dragon.
            rspeak(154) # BIRD ATTACKS DRAGON, BURNT TO A CINDER.
            dstroy(w['bird'])
            g['prop'][w['bird']] = 0 # Dead bird.
            if g['place'][w['snake']] == g['plac'][w['snake']]:
                g['tally2'] += 1 # Cannot find bird again.
            return {'fn':'newTurn', 'spk':0}
        elif g['obj'] == w['bear'] and at(w['troll']):
            rspeak(163) # TROLL SCURRIES AWAY.
            move(w['troll'], 0)
            move(w['troll']+100, 0)
            move(w['troll2'], g['plac'][w['troll']])
            move(w['troll2']+100, g['fixd'][w['troll']])
            juggle(w['chasm'])
            g['prop'][w['troll']] = 2
        elif (g['obj'] != w['vase'] or g['loc'] == g['plac'][w['pillow']]):
            rspeak(54) # OK
        else:
            g['prop'][w['vase']] = 2 # VASE DROPS WITH A DELICATE CRASH.
            if at(w['pillow']):
                g['prop'][w['vase']] = 0 # VASE RESTING ON VELVET PILLOW.
            pspeak(w['vase'], g['prop'][w['vase']]+1)
            if g['prop'][w['vase']] != 0:
                g['fixed'][w['vase']] = -1 # Vase destroyed.
    return {'fn':'newTurn', 'spk':0}

def drink(spk):
    # DRINK.  If no object, assume water and look for it here.  If water is
    # in the bottle, drink that, else must be at a water loc, so drink
    # stream.
    #
    # spk is default message, i.e., spk == g['actspk'][g['verb']]

    if (g['obj'] == 0                      # No object specified
        and liqloc(g['loc']) != w['water'] # and no water here
        and (liq() != w['water']           # and (no water in bottle
            or not here(w['bottle']))):    #     or no bottle here)
        return what()
    if g['obj'] != 0 and g['obj'] != w['water']: # obj not water.
        spk = 110 # DON'T BE RIDICULOUS!
    if spk == 110 or liq() != w['water'] or not here(w['bottle']):
        return {'fn':'newTurn', 'spk':spk}
    g['prop'][w['bottle']] = 1 # Bottle empty.
    g['place'][w['water']] = 0 # No water here.
    spk = 74 # THE BOTTLE OF WATER IS NOW EMPTY.
    return {'fn':'newTurn', 'spk':spk}

def drop(obj, where):
    '''
    Place an object at a given loc, prefixing it onto the atloc list.  Decr
    holdng if the object was being toted.
    '''

    global g

    if obj <= 100: # Only object numbers are < 100.
        if g['place'][obj] == -1: # If object is here,
            c['holdng'] -= 1 # Toting one less object.
        g['place'][obj] = where
    else:
        g['fixed'][obj-100] = where
    if where <= 0:
        return
    g['link'][obj] = g['atloc'][where]
    g['atloc'][where] = obj

def dstroy(obj):
    '''
    Permanently eliminate "object" by moving to a non-existent location.
    '''
    move(obj, 0)

def dwarvesDisturbed():
    # Oh dear, he's disturbed the dwarves.
    rspeak(136) # RUCKUS HAS AWAKENED THE DWARVES
    finish()

def eat(spk, intransitive=True):
    # EAT. Intransitive: assume food if present, else ask what.
    # Transitive: food ok, some things lose appetite, rest are ridiculous.

    if intransitive:
        if not here(w['food']):
            return what()
        dstroy(w['food'])
        spk = 72 # THANK YOU, IT WAS DELICIOUS!
    else:
        if g['obj'] == w['food']:
            dstroy(w['food'])
            spk = 72 # THANK YOU, IT WAS DELICIOUS!
        elif g['obj'] in [w['bird'], w['snake'], w['clam'], w['oyster'],
            w['dwarf'], w['dragon'], w['troll'], w['bear']]:
            spk = 71 # I THINK I JUST LOST MY APPETITE.
    return {'fn':'newTurn', 'spk':spk}

def feed(spk):
    # FEED.  If bird, no seed.  Snake, dragon, troll: quip.  If dwarf, make
    # him mad.  Bear, special.
    global g

    if g['obj'] == w['bird']:
        spk = 100 # HAVE NO BIRD SEED.
    elif g['obj'] in [w['snake'], w['dragon'], w['troll']]:
        spk = 102 # NOTHING HERE IT WANTS TO EAT (EXCEPT PERHAPS YOU).
        if g['obj'] == w['dragon'] and g['prop'][w['dragon']] != 0:
            spk = 110 # DON'T BE RIDICULOUS!
        if g['obj'] == w['troll']:
            spk = 182 # GLUTTONY IS NOT ONE OF THE TROLL'S VICES.
        if not (g['obj'] != w['snake'] or c['closed'] or not here(w['bird'])):
            spk = 101 # THE SNAKE HAS NOW DEVOURED YOUR BIRD.
            dstroy(w['bird'])        # Remove bird.
            g['prop'][w['bird']] = 0 # Dead bird.
            g['tally2'] += 1         # Cannot find bird again.
    elif g['obj'] == w['dwarf']:
        if here(w['food']):
            spk = 103 # YOU FOOL, DWARVES EAT ONLY COAL!
            c['dflag'] += 1
    elif g['obj'] == w['bear']:
        if g['prop'][w['bear']] == 0: # Locked to chain.
            spk = 102 # NOTHING HERE IT WANTS TO EAT (EXCEPT PERHAPS YOU).
        if g['prop'][w['bear']] == 3: # Dead bear.
            spk = 110 # DON'T BE RIDICULOUS!
        if here(w['food']):
            dstroy(w['food'])
            g['prop'][w['bear']] = 1 # Free and fed.
            g['fixed'][w['axe']] = 0
            g['prop'][w['axe']] = 0
            spk = 168 # WOLFS DOWN FOOD, CALMS DOWN.
        return {'fn':'newTurn', 'spk':spk}
    else:
        spk = 14 # I'M GAME.  WOULD YOU CARE TO EXPLAIN HOW?
    return {'fn':'newTurn', 'spk':spk}

def feeFie():
    # FEE FIE FOE FOO (and FUM).  Advance to next state if given in proper
    # order.  Look up wd1 in section 3 of vocab to determine which word we've
    # got.  Last word zips the eggs back to the Giant Room (unless already
    # there).

    global c, g

    k = vocab(g['wd1'],3) # FEE -> k==3001%1000==1, etc.
    spk = 42 # NOTHING HAPPENS.
    if c['foobar'] != 1 - k:
        if c['foobar'] != 0:
            spk = 151 # CAN'T YOU READ?  NOW YOU'D BEST START OVER.
        return {'fn':'newTurn', 'spk':spk}
    c['foobar'] = k # Track progress (word num) saying FEE FIE FOE FOO.
    if k != 4:
        return {'fn':'newTurn', 'spk':54} # newTurn()
    c['foobar'] = 0
    if (g['place'][w['eggs']] == g['plac'][w['eggs']] # cur loc == orig loc.
        or (toting(w['eggs']) and g['loc'] == g['plac'][w['eggs']])):
        return {'fn':'newTurn', 'spk':spk}
    # Bring back troll if we steal the eggs back from him before crossing.
    if (g['place'][w['eggs']] == 0 and g['place'][w['troll']] == 0
        and g['prop'][w['troll']] == 0):
        g['prop'][w['troll']] = 1 # Troll is back.
    k = 2                                 # DONE! Default message.
    if here(w['eggs']):                   # If eggs here, take them.
        k = 1 # NEST OF GOLDEN EGGS VANISHED!
    if g['loc'] == g['plac'][w['eggs']]:  # In Giant Room, bring eggs back.
        k = 0 # LARGE NEST HERE, FULL OF GOLDEN EGGS!
    move(w['eggs'], g['plac'][w['eggs']]) # Zip eggs to Giant Room.
    pspeak(w['eggs'], k)
    return {'fn':'newTurn', 'spk':0}

def fill(spk):
    # FILL.  Bottle must be empty, and some liquid available.  (Vase is nasty.)

    if g['obj'] != w['vase']:
        if g['obj'] != 0 and g['obj'] != w['bottle']:
            return {'fn':'newTurn', 'spk':spk}
        if g['obj'] == 0 and not here(w['bottle']):
            return what()
        spk = 107 # YOUR BOTTLE IS NOW FULL OF WATER.
        if liqloc(g['loc']) == 0:
            spk = 106 # THERE IS NOTHING HERE WITH WHICH TO FILL THE BOTTLE.
        if liq() != 0:
            spk = 105 # YOUR BOTTLE IS ALREADY FULL.
        if spk != 107:
            return {'fn':'newTurn', 'spk':spk}
        g['prop'][w['bottle']] = g['cond'][g['loc']]%4//2*2
        k = liq()
        if toting(w['bottle']):
            g['place'][k] = -1
        if k == w['oil']:
            spk = 108 # YOUR BOTTLE IS NOW FULL OF OIL.
        return {'fn':'newTurn', 'spk':spk}
    spk = 29 # YOU AREN'T CARRYING IT!
    if liqloc(g['loc']) == 0:
        spk = 144 # THERE IS NOTHING HERE WITH WHICH TO FILL THE VASE.
    if liqloc(g['loc']) == 0 or not toting(w['vase']):
        return {'fn':'newTurn', 'spk':spk}
    rspeak(145) # TEMPERATURE HAS DELICATELY SHATTERED THE VASE.
    g['prop'][w['vase']] = 2
    g['fixed'][w['vase']] = -1
    return discard(spk, goto9021=True)

def find(spk, k):
    #  FIND.  Might be carrying it, or it might be here.  Else give caveat.

    if (at(g['obj']) or (liq() == g['obj'] and at(w['bottle']))
        or k == liqloc(g['loc'])):
        spk = 94 # I BELIEVE WHAT YOU WANT IS RIGHT HERE WITH YOU.
    for i in range(1, 5+1):
        if (g['dloc'][i] == g['loc'] and c['dflag'] >= 2
            and g['obj'] == w['dwarf']):
            spk = 94 # I BELIEVE WHAT YOU WANT IS RIGHT HERE WITH YOU.
    if c['closed']:
        spk = 138 # I DARESAY WHATEVER YOU WANT IS AROUND HERE SOMEWHERE.
    if toting(g['obj']):
        spk = 24 # YOU ARE ALREADY CARRYING IT!
    return {'fn':'newTurn', 'spk':spk}

def finish(scorng=False):
    global g, w

    #  Exit code.

    #  The present scoring algorithm is as follows:
    #     Objective:          Points:        Present Total Possible:
    #  Getting well into cave   25                    25
    #  Each treasure < chest    12                    60
    #  Treasure chest itself    14                    14
    #  Each treasure > chest    16                   144
    #  Surviving             (max-num)*10             30
    #  Not quitting              4                     4
    #  Reaching "closng"        25                    25
    #  "Closed": Quit/killed    10
    #            Klutzed        25
    #            Wrong way      30
    #            Success        45                    45
    #  Came to Witt's End        1                     1
    #  Round out the total       2                     2
    #                                       Total:   350
    #  (Points can also be deducted for using hints.)

    score = 0
    mxscor = 0

    #  First tally up the treasures.  Must be in building and not broken.
    #  Give the poor guy 2 points just for finding each treasure.
    for i in range(50, g['maxtrs']+1):
        if g['ptext'][i] == 0:
            continue
        k = 12                # Easily found treasures.
        if i == w['chest']:   # Treasure chest.
            k = 14
        if i > w['chest']:    # Hard to find treasures.
            k = 16
        if g['prop'][i] >= 0: # Free 2 pts.  Treasure found, maybe not in bldg.
            score += 2
        if g['place'][i] == 3 and g['prop'][i] == 0: # In bldg & not broken.
            score += k - 2    # In bldg, so take back free 2 points.
        mxscor += k

    # Now look at how he finished and how far he got.  Maxdie and numdie tell
    # us how well he survived.  Gaveup says whether he exited via quit.
    # Dflag will tell us if he ever got suitably deep into the cave.  Closng
    # still indicates whether he reached the endgame.  And if he got as far
    # as "cave closed" (indicated by "closed"), then bonus is zero for
    # mundane exits or 133, 134, 135 if he blew it (so to speak).
    score += (c['maxdie'] - c['numdie'])*10
    mxscor += c['maxdie']*10
    if not (scorng or c['gaveup']):
        score += 4
    mxscor += 4
    if c['dflag'] != 0:
        score += 25
    mxscor += 25
    if c['closng']:
        score += 25
    mxscor += 25
    if c['closed']:
        if c['bonus'] ==   0: score += 10
        if c['bonus'] == 135: score += 25
        if c['bonus'] == 134: score += 30
        if c['bonus'] == 133: score += 45
    mxscor += 45

    # Did he come to Witt's End as he should?
    if g['place'][w['magzin']] == 108: # 108 is Witt's End.
        score += 1
    mxscor += 1

    # Round it off.
    score += 2
    mxscor += 2

    # Deduct points for hints.  Hints < 4 are special; see database description.
    for i in range(1, g['hntmax']+1):
        if g['hinted'][i]:
            score -= g['hints'][i][2]

    # Return to score command if that's where we came from.
    if scorng:
        return score,mxscor

    # That should be good enough.  Let's tell him all about it.
    print('\n\n\n YOU SCORED%4d OUT OF A POSSIBLE%4d USING%5d TURNS.'
        % (score,mxscor,c['turns']))

    for i in range(1, g['clsses']+1):
        if g['cval'][i] >= score:
            break
    else:
        print('\n YOU JUST WENT OFF MY SCALE!!\n')
        sys.exit(0)

    speak(g['ctext'][i])
    if i == g['clsses']-1:
        print('\n TO ACHIEVE THE NEXT HIGHER RATING ',
        'WOULD BE A NEAT TRICK!\n\n CONGRATULATIONS!!\n')
    else:
        k = g['cval'][i] + 1-score
        kk = 'S.'
        if k == 1:
            kk = '. '
        print('\n TO ACHIEVE THE NEXT HIGHER RATING, '
            'YOU NEED%3d MORE POINT%2s\n' % (k,kk))
    sys.exit(0)

def foobarEtc(verb):
    # Every input, check "foobar" flag.  If zero, nothing's going on.  If pos,
    # make neg.  If neg, he skipped a word, so make it zero.

    global c, g, wizcom

    # Line 2608
    c['foobar'] = min(0, -c['foobar'])
    if c['turns'] == 0 and g['wd1'] == 'MAGIC' and g['wd2'] == 'MODE':
        maint() # Game eventually exits if he's a wizard..
        return {'fn':'newTurn', 'spk':0}
    c['turns'] += 1
    if c['demo'] and c['turns'] >= wizcom['short']:
        closeDemo() # Game exits.
    if c['turns'] == 3:
        c['xxd'],c['xxt'] = datime()
    if c['turns'] == 45:
        # See if timer UUO has been zapped; if so, he's cheating.
        yyd,yyt = datime()
        if c['xxd'] == yyd and c['xxt'] == yyt:
            c['saved'] = 0
    if verb == w['say'] and g['wd2'] != '':
        verb = 0
    if verb == w['say']:
        return say()
    if g['tally'] == 0 and g['loc'] >= 15 and g['loc'] != 33:
        c['clock1'] -= 1 # Hall of Mists or beyond, but not Y2.
    if c['clock1'] == 0:
        return closeClock1()
    if c['clock1'] < 0:
        c['clock2'] -= 1
    if c['clock2'] == 0:
        return closeClock2() # goto 2
    if g['prop'][w['lamp']] == 1:
        g['limit'] -= 1
    if (g['limit'] <= 30 and here(w['batter']) and g['prop'][w['batter']] == 0
        and here(w['lamp'])):
        return lampRecharge()
    if g['limit'] == 0:
        return lampOut()
    if g['limit'] < 0 and g['loc'] <= 8:
        lampOutQuit() # Game exits.
    if g['limit'] <= 30:
        return lampNeedBatteries()
    return parseWords()

def getHint(hint):
    '''
    Hints

    Come here if he's been long enough at required loc(s) for some unused hint.
    Hint number is in variable "hint".  Branch to quick test for additional
    conditions, then come back to do neat stuff.  Goto 40010 if conditions are
    met and we want to offer the hint.  Goto 40020 to clear hintlc back to zero,
    40030 to take no action yet.
    '''

    # Now for the quick tests.  See database description for one-line notes.
    match hint:
        case 4: # Cave
            if g['prop'][w['grate']] != 0 or here(w['keys']):
                g['hintlc'][hint] = 0
                return
        case 5: # Bird
            if not (here(w['bird']) and toting(w['rod'])
                and g['oldobj'] == w['bird']):
                return
        case 6: # Snake
            if not here(w['snake']) or here(w['bird']):
                g['hintlc'][hint] = 0
                return
        case 7: # Maze
            if (g['atloc'][g['loc']] != 0 or g['atloc'][g['oldloc']] != 0
                or g['atloc'][g['oldlc2']] != 0 or c['holdng'] <= 1):
                g['hintlc'][hint] = 0
                return
        case 8: # Dark
            if not (g['prop'][w['emrald']] != -1
                and g['prop'][w['pyram']] == -1):
                g['hintlc'][hint] = 0
                return
        case 9: # Witt
            pass
        case _:
            bug(27) # Hint number exceeds goto list.

    g['hintlc'][hint] = 0
    if not yes(g['hints'][hint][3],0,54):
        return
    print('\n I AM PREPARED TO GIVE YOU A HINT, BUT IT WILL COST YOU',
        '%2d POINTS.' % g['hints'][hint][2])
    g['hinted'][hint] = yes(175, g['hints'][hint][4], 54) # WANT THE HINT?
    if g['hinted'][hint] and g['limit'] > 30:
        g['limit'] += 30*g['hints'][hint][2]
    g['hintlc'][hint] = 0

def getin(five=False):

#  Get a command from the adventurer.  Snarf out the first word, pad it with
#  blanks, and return it in word1.  Chars 6 thru 10 are returned in word1x, in
#  case we need to print out the whole word in an error message.  Any number of
#  blanks may follow the word.  If a second word appears, it is returned in
#  word2 (chars 6 thru 10 in word2x), else word2 is set to zero.

    word1 = word1x = word2 = word2x = ''
    while True:
        word = inputCheck().upper().split() # Expecting 1 or 2 words.
        n = len(word)
        if n > 2:
            print('\n PLEASE STICK TO 1- AND 2-WORD COMMANDS.\n')
            continue
        fmt = '%5s' if five else '%s'
        if n == 2:
            w = word[1]
            word2  = fmt % w[:5]
            word2x = fmt % w[5:]
        if n >= 1:
            w = word[0]
            word1  = fmt % w[:5]
            word1x = fmt % w[5:]
        if n > 0:
            break
    return word1, word1x, word2, word2x

def globalsInit():
    g = {
        'lines' :[''], # Ensure first real line is at index 1, like in Fortran.
        'linuse':0,
        'linbytes':0,
        'travel':751*[0],
        'ktab'  :301*[0],
        'atab'  :301*[''],
        'ltext' :151*[0],
        'stext' :151*[0],
        'key'   :151*[0],
        'cond'  :151*[0],
        'abb'   :151*[0], # Abbreviated description at loc.

        'atloc' :151*[0],
        'plac'  :101*[0],
        'place' :101*[0],
        'fixd'  :101*[0],
        'fixed' :101*[0],
        'link'  :201*[0],
        'ptext' :101*[0], # Property text.
        'prop'  :101*[0], # Print ptext[n] message for prop[n].
        'actspk': 36*[0], # Default message for an action.
        'rtext' :206*[0],
        'ctext' : 13*[0],
        'cval'  : 13*[0],
        'hintlc': 21*[0],
        'hinted': 21*[False],
        'hints' : [[0 for c in range(5)] for r in range(21)], # 21x5.
        'mtext' : 36*[0],
        'dseen' :  7*[False],
        'dloc'  :  7*[0],
        'odloc' :  7*[0],

        'linsiz':9650,
        'trvsiz': 750,
        'tabsiz': 300,
        'locsiz': 150,
        'vrbsiz':  35,
        'rtxsiz': 205,
        'clsmax':  12,
        'hntsiz':  20,
        'magsiz':  35,
        'setup':    0,
        'blklin':True,

        'clsses':1,
        'knfloc':-1,
        'loc':-1,
        'newloc':-1,
        'oldloc':-1,
        'oldlc2':-1,
        'trvs':1,
        'obj':0,
        'verb':0
    }
    return g

def goBack(kk):
    # Handle "GO BACK".  Look for verb which goes from loc to oldloc, or to
    # oldlc2 if oldloc has forced-motion.  K2 saves entry -> forced loc ->
    # previous loc.

    # Line 20
    k = g['oldloc']
    if forced(k):
        k = g['oldlc2']
    g['oldlc2'] = g['oldloc']
    g['oldloc'] = g['loc']
    k2 = 0
    if k == g['loc']:
        rspeak(91) # I NO LONGER REMEMBER HOW YOU GOT HERE.
        return {'fn':None}
    while True:
        ll = (abs(g['travel'][kk])//1000)%1000
        if ll == k:
            k = abs(g['travel'][kk])%1000
            kk = g['key'][g['loc']]
            return {'fn':'newLocation', 'goto':9, 'verb':k, 'kk':kk}
        if ll <= 300:
            j = g['key'][ll]
            if forced(ll) and (abs(g['travel'][j])//1000)%1000 == k:
                k2 = kk
        if g['travel'][kk] < 0:
            break
        kk += 1
    kk = k2
    if kk == 0:
        rspeak(140) # YOU CAN'T GET THERE FROM HERE.
        return {'fn':None}
    k = abs(g['travel'][kk])%1000
    kk = g['key'][g['loc']]
    return {'fn':'newLocation', 'goto':9, 'verb':k, 'kk':-1}

def hours():

#  Announce the current hours when the cave is open for adventuring.  This info
#  is stored in wkday, wkend, and holid, where bit shift(1,n) is on iff the
#  hour from n:00 to n:59 is "prime time" (cave closed).  Wkday is for
#  weekdays, wkend for weekends, holid for holidays.  Next holiday is from
#  hbegin to hend.

    global wizcom

    print('')
    hoursx(wizcom['wkday'],'MON -',' FRI:')
    hoursx(wizcom['wkend'],'SAT -',' SUN:')
    hoursx(wizcom['holid'],'HOLID','AYS: ')
    d,t = datime()
    if wizcom['hend'] < d or wizcom['hend'] < wizcom['hbegin']:
        return
    if wizcom['hbegin'] <= d:
        print('\n TODAY IS A HOLIDAY, NAMELY %s' % wizcom['hname'])
        return
    d = wizcom['hbegin'] - d
    t = 'DAYS, '
    if d == 1:
        t = 'DAY, '
    print('\n THE NEXT HOLIDAY WILL BE IN%3d %5s NAMELY %s'
        % (d,t,wizcom['hname']))

def hoursShow():
    # HOURS.  Report current non-prime-time hours.

    mspeak(6) # COLOSSAL CAVE IS OPEN AT THE FOLLOWING HOURS:
    hours()
    return {'fn':'newTurn', 'spk':0}

def hoursx(h,day1,day2):
    '''
    Used by hours (above) to print hours for either weekdays or weekends.
    '''

    first = True 
    frm = -1
    if h == 0:
        print('          %-5s%-5s  OPEN ALL DAY' % (day1,day2))
        return
    while True:
        frm = frm + 1
        if (h & (1<<frm)) != 0:
            continue
        if frm >= 24:
            break
        till = frm
        while True:
            till += 1
            if not ((h & (1<<till)) == 0 and till != 24):
                break
        print('          %-5s%-5s%4d:00 TO%3d:00' % (day1,day2,frm,till))
        print('%20s%4d:00 TO%3d:00' % (' ',frm,till))
        first =  False 
        frm = till
    if first:
        print('          %-5s%-5s  CLOSED ALL DAY'% (day1,day2))

def inputCheck(s=' ', dtype=str, emptyOk=False):
    global c

    while True:
        try:
            reply = input(s).strip()
            if reply == '':
                if emptyOk:
                    if   dtype == bool: v = False
                    elif dtype == int:  v = 0
                    elif dtype == str:  v = ''
                    return v
                continue
            return dtype(reply)
        except ValueError:
            t = str(dtype)
            t = t[1+t.find("'"):] # Extract, e.g., int from "<class 'int'>".
            t = t[:t.rfind("'")]
            if t=='INT': t = 'INTEGER'
            print(' %s NEEDED.' % t.upper())
        except EOFError:
            break
        except KeyboardInterrupt:
            break
    c['gaveup'] = True
    quitGame(verify=False)

def intransitive(spk):

    # Analyse an intransitive verb (ie, no object given yet).
    # Line 4080

    verb = g['verb']
    match verb:
        case  1: return take(spk=spk)      # TAKE, now call newTurn(v)
        case  2: return what()             # DROP
        case  3: return what()             # SAY
        case  4: return locking()          # OPEN
        case  5: return newTurn(verb)      # NOTH
        case  6: return locking()          # LOCK
        case  7: return lampOn(spk)        # ON
        case  8: return lampOff(spk)       # OFF
        case  9: return what()             # WAVE
        case 10: return what()             # CALM
        case 11: return newTurn(verb, spk) # WALK
        case 12: return attack(spk)        # KILL
        case 13: return pour(spk)          # POUR
        case 14: return eat(spk)           # EAT
        case 15: return drink(spk)         # DRNK
        case 16: return what()             # RUB
        case 17: return what()             # TOSS
        case 18: return quitGame()         # QUIT
        case 19: return what()             # FIND
        case 20: return inventory()        # INVN
        case 21: return what()             # FEED
        case 22: return fill(spk)          # FILL
        case 23: return blast(spk)         # BLST
        case 24: return score()            # SCOR
        case 25: return feeFie()           # FOO
        case 26: return brief()            # BRF
        case 27: return read(spk)          # READ
        case 28: return what()             # BREK
        case 29: return what()             # WAKE
        case 30: return suspend()          # SUSP
        case 31: return hoursShow()        # HOUR
        case 32: return suspend(restart=True) # RESUM
        case  _: bug(23)     # Intransitive action verb exceeds goto list.

def inventory():
    #  INVENTORY.  If object, treat same as find.  Else report on current
    #  burden.

    spk = 98
    for i in range(1, 100+1):
        if i == w['bear'] or not toting(i):
            continue
        if spk == 98:
            rspeak(99) # YOU ARE CURRENTLY HOLDING THE FOLLOWING:
        g['blklin'] = False
        pspeak(i, -1)
        g['blklin'] = True
        spk = 0
    if toting(w['bear']):
        spk = 141 # YOU ARE BEING FOLLOWED BY A VERY LARGE, TAME BEAR.
    return {'fn':'newTurn', 'spk':spk}

def juggle(obj):
    '''
    Juggle an object by picking it up and putting it down again, the purpose
    being to get the object to the front of the chain of things at its loc.
    '''

    global g

    i = g['place'][obj]
    j = g['fixed'][obj]
    move(obj, i)
    move(obj+100, j)

def lampNeedBatteries():
    # Line 12200
    if c['lmwarn'] or not here(w['lamp']):
        return parseWords()
    c['lmwarn'] = True
    spk = 187 # GO BACK FOR THOSE BATTERIES.
    if g['place'][w['batter']] == 0:
        spk = 183 # START WRAPPING THIS UP...or FIND SOME FRESH BATTERIES.
    if g['prop'][w['batter']] == 1:
        spk = 189 # OUT OF SPARE BATTERIES.
    rspeak(spk)
    return parseWords()

def lampOff(spk):
    # Lamp off
    if not here(w['lamp']):
        return {'fn':'newTurn', 'spk':spk}
    g['prop'][w['lamp']] = 0
    rspeak(40) # YOUR LAMP IS NOW OFF.
    if dark():
        rspeak(16) # IT IS NOW PITCH DARK.
    return {'fn':'newTurn', 'spk':0}

def lampOn(spk):
    # Light lamp
    if not here(w['lamp']):
        return {'fn':'newTurn', 'spk':spk}
    spk = 184
    if g['limit'] < 0:
        return {'fn':'newTurn', 'spk':spk}
    g['prop'][w['lamp']] = 1
    rspeak(39) # YOUR LAMP IS NOW ON.
    if c['wzdark']:
        location()
    return {'fn':'newTurn', 'spk':0}

def lampOut():
    # Line 12400
    g['limit'] = -1
    g['prop'][w['lamp']] = 0
    if here(w['lamp']):
        rspeak(184) # YOUR LAMP HAS RUN OUT OF POWER.
    return parseWords()

def lampOutQuit():
    # Line 12600
    global w

    rspeak(185) # NOT MUCH POINT IN WANDERING AROUND WITHOUT A LAMP.
    c['gaveup'] = True
    finish()

def lampRecharge():
    '''
    Another way we can force an end to things is by having the lamp give out.
    When it gets close, we come here to warn him.  We go to 12000 if the lamp
    and fresh batteries are here, in which case we replace the batteries and
    continue.  12200 is for other cases of lamp dying.  12400 is when it goes
    out, and 12600 is if he's wandered outside and the lamp is used up, in
    which case we force him to give up.
    '''

    # Line 12000
    rspeak(188) # YOUR LAMP IS GETTING DIM...REPLACING BATTERIES.
    g['prop'][w['batter']] = 1
    if toting(w['batter']):
        drop(w['batter'],g['loc'])
    g['limit'] += 2500
    c['lmwarn'] = False
    return parseWords()

def location():
    # Describe the current location and (maybe) get next command.

    global c, g

    # Print text for current loc.
    if g['loc'] == 0:
        return dead(pit=False) # He's dead.
    kk = g['stext'][g['loc']]
    if g['abb'][g['loc']]%c['abbnum'] == 0 or kk == 0:
        kk = g['ltext'][g['loc']]
    if not (forced(g['loc']) or not dark()):
        if c['wzdark'] and pct(35):
            return dead()
        kk = g['rtext'][16] # IT IS NOW PITCH DARK
    if toting(w['bear']):
        rspeak(141) # FOLLOWED BY A VERY LARGE, TAME BEAR
    speak(kk)
    k = 1
    if forced(g['loc']):
        return {'fn':'newLocation', 'goto':8, 'verb':k, 'kk':-1}
    if g['loc'] == 33 and pct(25) and not c['closng']: # 1/4 chance at Y2.
        rspeak(8) # HOLLOW VOICE SAYS "PLUGH"

    # Print out descriptions of objects at this location.  If not closing and
    # property value is negative, tally off another treasure.  Rug is special
    # case; once seen, its prop is 1 (dragon on it) till dragon is killed.
    # Similarly for chain; prop is initially 1 (locked to bear).  These hacks
    # are because prop = 0 is needed to get full score.

    if dark():
        return {'fn':'newTurn', 'spk':0}
    g['abb'][g['loc']] += 1
    i = g['atloc'][g['loc']]
    obj = 0 # Added by mm.
    while True:
        if i == 0:
            return {'fn':'newTurn', 'spk':0}
        obj = i
        if obj > 100:
            obj -= 100
        if obj == w['steps'] and toting(w['nugget']):
            i = g['link'][i]
            continue
        else:
            if g['prop'][obj] < 0:
                if c['closed']:
                    i = g['link'][i]
                    continue
                g['prop'][obj] = 0
                if obj == w['rug'] or obj == w['chain']:
                    g['prop'][obj] = 1
                g['tally'] -= 1
                # If remaining treasures too elusive, zap his lamp.
                if g['tally'] == g['tally2'] and g['tally'] != 0:
                    g['limit'] = min(35, g['limit'])
            kk = g['prop'][obj]
            if obj == w['steps'] and g['loc'] == g['fixed'][w['steps']]:
                kk = 1
            pspeak(obj, kk)
            i = g['link'][i]

def locking(intransitive=True):
    #  Lock, unlock, no object given.  Assume various things if present.
    global g

    if intransitive:
        if here(w['clam']):
            g['obj'] = w['clam']
        if here(w['oyster']):
            g['obj'] = w['oyster']
        if at(w['door']):
            g['obj'] = w['door']
        if at(w['grate']):
            g['obj'] = w['grate']
        if g['obj'] != 0 and here(w['chain']):
            return what()
        if here(w['chain']):
            g['obj'] = w['chain']
        if g['obj'] == 0:
            spk = 28 # THERE IS NOTHING HERE WITH A LOCK!
            return {'fn':'newTurn', 'spk':spk}

    # Lock, unlock object.  Special stuff for opening clam/oyster and for
    # chain.

    if g['obj'] == w['clam'] or g['obj'] == w['oyster']: # Clam/oyster.
        k = 0
        if g['obj'] == w['oyster']:
            k = 1
        spk = 124+k
        if toting(g['obj']):
            spk = 120+k # PUT DOWN CLAM/OYSTER BEFORE OPENING IT.
        if not toting(w['tridnt']):
            spk = 122+k # NOTHING STRONG ENOUGH TO OPEN CLAM/OYSTER.
        if g['verb'] == w['lock']:
            spk = 61 # WHAT?
        if spk != 124: # GLISTENING PEARL FALLS OUT OF CLAM AND ROLLS AWAY.
            return {'fn':'newTurn', 'spk':spk}
        dstroy(w['clam'])
        drop(w['oyster'],g['loc']) # Give it its proper name!
        drop(w['pearl'],105) # Roll pearl to cul-de-sac, 2 rooms from oyster.
        return {'fn':'newTurn', 'spk':spk}
    if g['obj'] == w['door']:
        spk = 111 # DOOR IS EXTREMELY RUSTY AND REFUSES TO OPEN.
    if g['obj'] == w['door'] and g['prop'][w['door']] == 1:
        spk = 54 # OK
    if g['obj'] == w['cage']:
        spk = 32 # IT HAS NO LOCK.
    if g['obj'] == w['keys']:
        spk = 55 # YOU CAN'T UNLOCK THE KEYS.
    if g['obj'] == w['grate'] or g['obj'] == w['chain']:
        spk = 31 # YOU HAVE NO KEYS!
    if spk != 31 or not here(w['keys']):
        return {'fn':'newTurn', 'spk':spk}
    if g['obj'] == w['chain']: # Chain.
        if g['verb'] == w['lock']:
            spk = 172 # THE CHAIN IS NOW LOCKED.
            if g['prop'][w['chain']] != 0:
                spk = 34 # IT WAS ALREADY LOCKED.
            if g['loc'] != g['plac'][w['chain']]:
                spk = 173 # NOTHING HERE TO WHICH THE CHAIN CAN BE LOCKED.
            if spk != 172:
                return {'fn':'newTurn', 'spk':spk}
            g['prop'][w['chain']] = 2
            if toting(w['chain']):
                drop(w['chain'],g['loc'])
            g['fixed'][w['chain']] = -1
            return {'fn':'newTurn', 'spk':spk}
        spk = 171 # THE CHAIN IS NOW UNLOCKED.
        if g['prop'][w['bear']] == 0:
            spk = 41 # NO WAY TO GET PAST THE BEAR
        if g['prop'][w['chain']] == 0:
            spk = 37 # IT WAS ALREADY UNLOCKED.
        if spk != 171: # THE CHAIN IS NOW UNLOCKED.
            return {'fn':'newTurn', 'spk':spk}
        g['prop'][w['chain']] = 0
        g['fixed'][w['chain']] = 0
        if g['prop'][w['bear']] != 3: # ==3, dead bear.
            g['prop'][w['bear']] = 2 # Free.
        g['fixed'][w['bear']] = 2 - g['prop'][w['bear']]
        return {'fn':'newTurn', 'spk':spk}
    if not c['closng']:
        k = 34 + g['prop'][w['grate']] # GRATE NOW LOCKED/WAS LOCKED.
        g['prop'][w['grate']] = 1 # Unlocked.
        if g['verb'] == w['lock']:
            g['prop'][w['grate']] = 0 # Locked.
        k += 2*g['prop'][w['grate']]
        return {'fn':'newTurn', 'spk':k}
    if not c['panic']:
        c['clock2'] = 15
    c['panic'] = True
    k = 130 # THIS EXIT IS CLOSED.
    return {'fn':'newTurn', 'spk':k}

def lookAround():
    # LOOK.  Can't give more detail.  Pretend it wasn't dark (though it may
    # "now" be dark) so he won't fall into a pit while staring into the
    # gloom.

    if c['detail'] < 3:
        rspeak(15) # I AM NOT ALLOWED TO GIVE MORE DETAIL.
    c['detail'] += 1
    c['wzdark'] = False
    g['abb'][g['loc']] = 0
    return {'fn':None} #goto 2

def maint():

    '''
    Someone said the magic word to invoke maintenance mode.  Make sure he's a
    wizard.  If so, let him tweak all sorts of random things, then exit so
    can save tweaked version.  Since magic word must be first command given,
    only thing which needs to be fixed up is abb(1).
    '''

    global g, wizcom

    if not wizard():
        return
    g['blklin'] = False 
    if yesm(10,0,0): # DO YOU WISH TO SEE THE HOURS?
        hours()
    if yesm(11,0,0): # DO YOU WISH TO CHANGE THE HOURS?
        newhrs()
    if yesm(26,0,0): # DO YOU WISH TO (RE)SCHEDULE THE NEXT HOLIDAY?
        mspeak(27) # TO BEGIN HOW MANY DAYS FROM TODAY?
        wizcom['hbegin'] = inputCheck(dtype=int)
        mspeak(28) # TO LAST HOW MANY DAYS (ZERO IF NO HOLIDAY)?
        wizcom['hend'] = inputCheck(dtype=int)
        d,t = datime()
        wizcom['hbegin'] += d
        wizcom['hend'] += wizcom['hbegin'] - 1
        mspeak(29) # TO BE CALLED WHAT (UP TO 20 CHARACTERS)?
        wizcom['hname'] = inputCheck().upper()
    s = ' LENGTH OF SHORT GAME (NULL TO LEAVE AT%3d): ' % wizcom['short']
    x = inputCheck(s, dtype=int, emptyOk=True)
    if x > 0:
        wizcom['short'] = x
    mspeak(12, nl=False) # NEW MAGIC WORD (NULL TO LEAVE UNCHANGED):
    x = inputCheck(emptyOk=True)
    if x != '':
        wizcom['magic'] = x
    mspeak(13, nl=False) # NEW MAGIC NUMBER (NULL TO LEAVE UNCHANGED):
    x = inputCheck(dtype=int, emptyOk=True)
    if x > 0:
        wizcom['magnm'] = x
    s = ' LATENCY FOR RESTART (NULL TO LEAVE AT%3d): ' % wizcom['latncy']
    x = inputCheck(s, dtype=int, emptyOk=True)
    if 0 < x < 45:
        mspeak(30) # TOO SMALL!  ASSUMING MINIMUM VALUE (45 MINUTES).
    if x > 0:
        wizcom['latncy'] = max(45, x)
    if yesm(14,0,0): # DO YOU WISH TO CHANGE THE MESSAGE OF THE DAY?
        motd(True)
    c['saved'] = 0
    g['setup'] = 2
    g['abb'][1] = 0
    mspeak(15) # OKAY.  YOU CAN SAVE THIS VERSION NOW.
    g['blklin']= True 
    f = open('hours', 'w')
    for k in wizcom.keys():
        print('%s %s' % (k, str(wizcom[k])), file=f)
    f.close()
    ciao()

def motd(alter):
    '''
    Handles message of the day.  If alter is true, read a new message from
    the wizard.  Else print the current one.  Message is initially null.
    '''

    global wizcom

    msg = ''

    if not alter:
        if wizcom['motd'] != '':
            print(' %s' % wizcom['motd'])
        return
    mspeak(23) # LIMIT LINES TO 70 CHARS.  END WITH NULL LINE.
    while True:
        try:
            line = inputCheck(emptyOk=True).upper()
        except KeyboardInterrupt:
            c['gaveup'] = True
            quitGame(verify=False)
        if len(line) > 70:
            mspeak(24) # LINE TOO LONG, RETYPE:
            continue
        if line == '':
            wizcom['motd'] = msg
            return
        if len(msg)+len(line) >= 100: # Limit motd to 100 chars.
            mspeak(25) # NOT ENOUGH ROOM FOR ANOTHER LINE...
            wizcom['motd'] = msg
            return
        msg += line

def motionsSpecial(k):
    # Special motions come here.  Labelling convention: statement
    # numbers nnnxx (xx = 00-99) are used for special case number
    # nnn (nnn = 301-500).

    global g

    match g['newloc']-300: # goto (30100,30200,30300)newloc
        case 1: # loc is either 99/alcove or 100/plover.
            # Travel 301.  Plover-alcove passage.  Can carry only emerald.
            # Note: travel table must include "useless" entries going through
            # passage, which can never be used for actual motion, but can be
            # spotted by "go back".
#           g['newloc'] = 99 + 100 - g['loc']
            g['newloc'] = 99 if g['loc']==100 else 100 # Go to other end.
            if c['holdng'] == 0 or (c['holdng'] == 1 and toting(w['emrald'])):
                return {'fn':None} # goto 2 # Holding nothing or only emerald.
            g['newloc'] = g['loc'] # Don't move.
            rspeak(117) # WON'T FIT THROUGH THE TUNNEL WITH YOU.
            return {'fn':None} # goto 2
        case 2:
            # Travel 302.  Plover transport.  Drop the emerald (only use
            # special travel if toting it), so he's forced to use the
            # plover-passage to get it out.  Having dropped it, go back and
            # pretend he wasn't carrying it after all.
            drop(w['emrald'],g['loc'])
            return {'fn':'newLocation', 'goto':12, 'verb':k, 'kk':-1}
        case 3:
            # Travel 303.  Troll bridge.  Must be done only as special motion
            # so that dwarves won't wander across and encounter the bear.
            # (They won't follow the player there because that region is
            # forbidden to the pirate.)  If prop(troll) = 1, he's crossed
            # since paying, so step out and block him.  (Standard travel
            # entries check for prop(troll) = 0.)  Special stuff for bear.
            if g['prop'][w['troll']] != 1:
                g['newloc'] = (g['plac'][w['troll']]
                    + g['fixd'][w['troll']] - g['loc'])
                if g['prop'][w['troll']] == 0:
                    g['prop'][w['troll']] = 1
                if not toting(w['bear']):
                    return {'fn':None} # goto 2
                rspeak(162) # YOU STUMBLE BACK AND FALL INTO THE CHASM.
                g['prop'][w['chasm']] = 1
                g['prop'][w['troll']] = 2
                drop(w['bear'], g['newloc'])
                g['fixed'][w['bear']] = -1 # Destroy bear.
                g['prop'][w['bear']] = 3   # Dead bear.
                if g['prop'][w['spices']] < 0:
                    g['tally2'] += 1       # Cannot find spices again.
                g['oldlc2'] = g['newloc']
                return dead()
            pspeak(w['troll'], 1) # No msg, chased away.
            g['prop'][w['troll']] = 0
            move(w['troll2'], 0)
            move(w['troll2']+100, 0)
            move(w['troll'], g['plac'][w['troll']])
            move(w['troll']+100, g['fixd'][w['troll']])
            juggle(w['chasm'])
            g['newloc'] = g['loc']
            return {'fn':None} # goto 2
        case _:
            bug(20) # Special travel (500>l>300) exceeds goto list.

def move(obj,where):

    '''
    Place any object anywhere by picking it up and dropping it.  May already
    be toting, in which case the carry is a no-op.  Mustn't pick up objects
    which are not at any loc, since carry wants to remove objects from atloc
    chains.
    '''

    global g

    if obj <= 100:
        frm = g['place'][obj]
    else:
        frm = g['fixed'][obj-100]
    if 0 < frm <= 300:
        carry(obj, frm)
    drop(obj, where)

def newhrs():
    '''
    Set up new hours for the cave.  Specified as inverse--i.e., when is it
    closed due to prime time?  See hours (above) for desc of variables.
    '''

    global wizcom

    mspeak(21)
    wizcom['wkday'] = newhrx('WEEKD','AYS:')
    wizcom['wkend'] = newhrx('WEEKE','NDS:')
    wizcom['holid'] = newhrx('HOLID','AYS:')
    mspeak(22)
    hours()

def newhrx(day1,day2):
    '''
    Input prime time specs and set up a word of internal format.
    '''

    newhrx = 0
    print(' PRIME TIME ON %-5s%-5s' % (day1,day2))
    while True:
        frm = inputCheck(' FROM: ', dtype=int)
        if not (0 <= frm < 24):
            return newhrx
        till = inputCheck(' TILL: ', dtype=int)
        till -= 1
        if not (frm <= till < 24):
            return newhrx
        for i in range(frm, till+1):
            newhrx |= 1<<i

def newLocation(goto, k, kk=-1):
    '''
    Figure out the new location

    Given the current location in "loc", and a motion verb number in "k", put
    the new location in "newloc".  The current loc is saved in "oldloc" in
    case he wants to retreat.  The current oldloc is saved in oldlc2, in case
    he dies.  (If he does, newloc will be limbo, and oldloc will be what
    killed him, so we need oldlc2, which is the last place he was safe.)
    '''

    if goto == 8:
        # Line 8
        kk = g['key'][g['loc']]
        g['newloc'] = g['loc']
        if kk == 0:
            bug(26) # Location has no travel entries.
        if k == w['null']:
            return {'fn':None} # goto 2
        elif k == w['back']:
            return goBack(kk)
        elif k == w['look']:
            lookAround() # goto 2
            return {'fn':None} # goto 2
        elif k == w['cave']:
            caveMsg() # goto 2
            return {'fn':None} # goto 2
        g['oldlc2'] = g['oldloc']
        g['oldloc'] = g['loc']

    if goto <= 9:
        while True:
            # Line 9
            ll = abs(g['travel'][kk]) # travel[kk] is new loc.
            if ll%1000 in [1, k]:
                break
            if g['travel'][kk] < 0:
                return badMotion(k)
            kk += 1

    while True: # Line 10
        if goto < 12:
            ll //= 1000 # Newloc portion of ll.
        while True: # Check for conditional travel.
            if goto < 12: # Line 11
                g['newloc'] = ll//1000
                k = g['newloc']%100
                if g['newloc'] <= 300:
                    break # Not conditional travel.
                if g['prop'][k] != g['newloc']//100 - 3:
                    g['newloc'] = ll%1000 # Line 16
                    if g['newloc'] <= 300:
                        return {'fn':None} # goto 2
                    if g['newloc'] <= 500:
                        return motionsSpecial(k)
                    rspeak(g['newloc']-500)
                    g['newloc'] = g['loc']
                    return {'fn':None} # goto 2
            while True: # Line 12
                if g['travel'][kk] < 0:
                    bug(25) # Conditional travel entry with no alternative.
                kk += 1
                g['newloc'] = abs(g['travel'][kk])//1000
                if g['newloc'] == ll:
                    continue
                ll = g['newloc']
                break
            goto = 11

        # Line 13
        if g['newloc'] <= 100: # Line 13
            goto = 14
        elif toting(k) or (g['newloc'] > 200 and at(k)):
            goto = 16
        else:
            goto = 12
            continue
        if goto==14 and g['newloc']!=0 and not pct(g['newloc']): # Line 14
            goto = 12
            continue
        g['newloc'] = ll%1000 # Line 16
        if g['newloc'] <= 300:
            return {'fn':None} # goto 2
        if g['newloc'] <= 500:
            return motionsSpecial(k)
        rspeak(g['newloc']-500)
        g['newloc'] = g['loc']
        return {'fn':None} # goto 2
    if g['newloc'] > 300:
        if g['newloc'] <= 500:
            return motionsSpecial(k)
        rspeak(g['newloc']-500)
        g['newloc'] = g['loc']
    return {'fn':None} # goto 2

def newTurn(verb, spk=54): # 54 is number for OK.
    global g

    if spk > 0:
        rspeak(spk)
    if spk > -1: # A poor way to implement GOTO 2012.
        verb = 0 # Line 2012
        g['oldobj'] = g['obj']
        g['obj'] = 0

    # Check if this loc is eligible for any hints.  If been here long enough,
    # branch to help section (on later page).  Hints all come back here
    # eventually to finish the loop.  Ignore "hints" < 4 (special stuff, see
    # database notes).

    # Many GOTO 2600
    for hint in range(4, g['hntmax']+1): # Line 2600
        if g['hinted'][hint]:
            continue
        if not bitset(g['loc'],hint):
            g['hintlc'][hint] = -1
        g['hintlc'][hint] += 1
        if g['hintlc'][hint] >= g['hints'][hint][1]:
            getHint(hint)

    #  Kick the random number generator just to add variety to the chase.  Also,
    #  if closing time, check for any objects being toted with prop < 0 and set
    #  the prop to -1-prop.  This way objects won't be described until they've
    #  been picked up and put down separate from their respective piles.  Don't
    #  tick clock1 unless well into cave (and not at Y2).

    if c['closed']:
        if g['prop'][w['oyster']] < 0 and toting(w['oyster']):
            pspeak(w['oyster'], 1) # SOMETHING WRITTEN ON UNDERSIDE OF OYSTER.
        for i in range(1, 100+1):
            if toting(i) and g['prop'][i] < 0:
                g['prop'][i] = -1 - g['prop'][i]
    c['wzdark'] = dark()
    if g['knfloc'] > 0 and g['knfloc'] != g['loc']:
        g['knfloc'] = 0
    random()
    g['wd1'],g['wd1x'],g['wd2'],g['wd2x'] = getin()
    return foobarEtc(verb)

def parseWords():
    # Line 19999
    k = 43 # WHERE?
    if liqloc(g['loc']) == w['water']:
        k = 70 # YOUR FEET ARE NOW WET.
    if g['wd1'] == 'ENTER' and (g['wd2'] in ['STREA', 'WATER']):
        return {'fn':'newTurn', 'spk':k}
    if g['wd1'] == 'ENTER' and g['wd2'] != '':
        return secondWord() # Move wd2 to wd1.
    if (g['wd1'] in ['WATER', 'OIL'] and g['wd2'] in ['PLANT', 'DOOR']
        and at(vocab(g['wd2'],1))): # Use liquid name as verb POUR.
        g['wd2'] = 'POUR'
    westOrW()
    return analyseWord()

def postDbInit():
    # Finish constructing internal data format
    global c, g, w, wizcom

    # If setup = 2 we don't need to do this.  It's only necessary if we
    # haven't done it at all or if the program has been run since then.
    if g['setup'] == 2:
        return
    if g['setup'] == -1:
        suspend(restart=True)

    # Having read in the database, certain things are now constructed.  Props
    # are set to zero.  We finish setting up cond by checking for
    # forced-motion travel entries.  The plac and fixd arrays are used to set
    # up atloc[n] as the first object at location n, and link[obj] as the
    # next object at the same location as obj.  (Obj>100 indicates that
    # fixed(obj-100) = loc; link[obj] is still the correct link to use.)  Abb
    # is zeroed; it controls whether the abbreviated description is printed.
    # Counts mod 5 unless "look" is used.
    for i in range(1, 100+1):
        g['place'][i] = 0
        g['prop'][i] = 0
        g['link'][i] = 0
        g['link'][i+100] = 0
    for i in range(1, g['locsiz']+1):
        g['abb'][i] = 0
        if g['ltext'][i] != 0 and g['key'][i] != 0:
            k = g['key'][i]
            if abs(g['travel'][k])%1000 == 1:
                g['cond'][i] = 2 # Forced movement at this location.
        g['atloc'][i] = 0

    #  Set up the atloc and link arrays as described above.  We'll use the
    #  drop subroutine, which prefaces new objects on the lists.  Since we
    #  want things in the other order, we'll run the loop backwards.  If the
    #  object is in two locs, we drop it twice.  This also sets up "place"
    #  and "fixed" as copies of "plac" and "fixd".  Also, since two-placed
    #  objects are typically best described last, we'll drop them first.
    for i in range(1, 100+1):
        k = 101 - i
        if g['fixd'][k] <= 0:
            continue
        drop(k+100, g['fixd'][k])
        drop(k, g['plac'][k])
    for i in range(1, 100+1):
        k = 101 - i
        g['fixed'][k] = g['fixd'][k]
        if g['plac'][k] != 0 and g['fixd'][k] <= 0:
            drop(k, g['plac'][k])

    # Treasures, as noted earlier, are objects 50 through maxtrs (currently
    # 79).  Their props are initially -1, and are set to 0 the first time
    # they are described.  Tally keeps track of how many are not yet found,
    # so we know when to close the cave.  Tally2 counts how many can never be
    # found (e.g. if lost bird or bridge).
    g['maxtrs'] = 79
    g['tally'] = 0
    g['tally2'] = 0
    for i in range(50, g['maxtrs']+1): # Go through treasures, which are >50.
        if g['ptext'][i] != 0: # ==0 means no object info here.
            g['prop'][i] = -1 # Treasure not yet found.
        g['tally'] -= g['prop'][i]

    # Clear the hint stuff.  hintlc[i] is how long he's been at loc with
    # cond bit i.  hinted[i] is true iff hint i has been used.
    for i in range(1, g['hntmax']+1):
        g['hinted'][i] = False
        g['hintlc'][i] = 0

    #  Define some handy mnemonics.  These correspond to object numbers.
    w = { # 'w' for words.
        'keys':vocab('KEYS',1),
        'lamp':vocab('LAMP',1),
        'grate':vocab('GRATE',1),
        'cage':vocab('CAGE',1),
        'rod':vocab('ROD',1),
        'rod2':vocab('ROD',1) + 1,
        'steps':vocab('STEPS',1),
        'bird':vocab('BIRD',1),
        'door':vocab('DOOR',1),
        'pillow':vocab('PILLO',1),
        'snake':vocab('SNAKE',1),
        'fissur':vocab('FISSU',1),
        'tablet':vocab('TABLE',1),
        'clam':vocab('CLAM',1),
        'oyster':vocab('OYSTE',1),
        'magzin':vocab('MAGAZ',1),
        'dwarf':vocab('DWARF',1),
        'knife':vocab('KNIFE',1),
        'food':vocab('FOOD',1),
        'bottle':vocab('BOTTL',1),
        'water':vocab('WATER',1),
        'oil':vocab('OIL',1),
        'plant':vocab('PLANT',1),
        'plant2':vocab('PLANT',1) + 1,
        'axe':vocab('AXE',1),
        'mirror':vocab('MIRRO',1),
        'dragon':vocab('DRAGO',1),
        'chasm':vocab('CHASM',1),
        'troll':vocab('TROLL',1),
        'troll2':vocab('TROLL',1) + 1,
        'bear':vocab('BEAR',1),
        'messag':vocab('MESSA',1),
        'vend':vocab('VENDI',1),
        'batter':vocab('BATTE',1),

        # Objects from 50 through whatever are treasures.  Here are a few.,
        'nugget':vocab('GOLD',1),
        'coins':vocab('COINS',1),
        'chest':vocab('CHEST',1),
        'eggs':vocab('EGGS',1),
        'tridnt':vocab('TRIDE',1),
        'vase':vocab('VASE',1),
        'emrald':vocab('EMERA',1),
        'pyram':vocab('PYRAM',1),
        'pearl':vocab('PEARL',1),
        'rug':vocab('RUG',1),
        'chain':vocab('CHAIN',1),
        'spices':vocab('SPICE',1),

        # These are motion-verb numbers.,
        'back':vocab('BACK',0),
        'look':vocab('LOOK',0),
        'cave':vocab('CAVE',0),
        'null':vocab('NULL',0),
        'entrnc':vocab('ENTRA',0),
        'dprssn':vocab('DEPRE',0),

        # And some action verbs.,
        'say':vocab('SAY',2),
        'lock':vocab('LOCK',2),
        'throw':vocab('THROW',2),
        'find':vocab('FIND',2),
        'invent':vocab('INVEN',2)
    }

    '''
    Initialise the dwarves.  Dloc is loc of dwarves, hard-wired in.  Odloc is
    prior loc of each dwarf, initially garbage.  Daltlc is alternate initial loc
    for dwarf, in case one of them starts out on top of the adventurer.  (No 2
    of the 5 initial locs are adjacent.)  Dseen is true if dwarf has seen him.
    Dflag controls the level of activation of all this:
       0     No dwarf stuff yet (wait until reaches hall of mists)
       1     Reached hall of mists, but hasn't met first dwarf
       2     Met first dwarf, others start moving, no knives thrown yet
       3     A knife has been thrown (first set always misses)
       3+    Dwarves are mad (increases their accuracy)
    Sixth dwarf is special (the pirate).  He always starts at his chest's
    eventual location inside the maze.  This loc is saved in chloc for ref.
    The dead end in the other maze has its loc stored in chloc2.
    '''
    g['chloc'] = 114 # DEAD END
    g['chloc2'] = 140 # DEAD END
    g['dseen'][1:6+1] = 6*[False]
    g['dflag'] = 0
    g['dloc'][1] = 19 # HALL OF THE MOUNTAIN KING
    g['dloc'][2] = 27 # WEST SIDE OF FISSURE IN HALL OF MISTS
    g['dloc'][3] = 33 # LARGE ROOM "Y2" ON A ROCK
    g['dloc'][4] = 44 # TWISTY LITTLE PASSAGES, ALL ALIKE
    g['dloc'][5] = 64 # COMPLEX JUNCTION LARGE ROOM ABOVE
    g['dloc'][6] = g['chloc']
    g['daltlc'] = 18 # NUGGET OF GOLD ROOM

    '''
    Other random flags and counters, as follows:
     turns   Tallies how many commands he's given (ignores yes/no)
     limit   Lifetime of lamp (not set here)
     iwest   How many times he's said "WEST" instead of "W"
     knfloc  0 if no knife here, loc if knife here, -1 after caveat
     detail  How often we've said "not allowed to give more detail"
     abbnum  How often we should print non-abbreviated descriptions
     maxdie  Number of reincarnation messages available (up to 5)
     numdie  Number of times killed so far
     holdng  Number of objects being carried
     dkill   Number of dwarves killed (unused in scoring, needed for msg)
     foobar  Current progress in saying "FEE FIE FOE FOO".
     bonus   Used to determine amount of bonus if he reaches closing
     clock1  Number of turns from finding last treasure till closing
     clock2  Number of turns from first warning till blinding flash
     Logicals were explained earlier
    '''

    c = { # 'c' for cave state.
        'abbnum':5,
        'bonus':0,
        'clock1':30,
        'clock2':50,
        'closed':False,
        'closng':False,
        'demo':False,
        'detail':0,
        'dflag':False,
        'dkill':0,
        'foobar':0,
        'gaveup':False,
        'holdng':0,
        'iwest':0,
        'knfloc':0,
        'lmwarn':False,
        'numdie':0,
        'panic':False,
        'saved':0,
        'savet':0,
        'scorng':False,
        'turns':0,
        'wzdark':False,
        'yea':False
    }
    for i in range(4+1):
        if g['rtext'][2*i+81] != 0:
            c['maxdie'] = i + 1

    # If setup = 1, report on amount of arrays actually used, to permit
    # reductions.
#   if g['setup'] != 1:
#       return
    g['setup'] = 2

    for kk in range(g['locsiz'], 0, -1): # Section 1.
        if g['ltext'][kk] != 0:
            break
    g['obj'] = 0
    for k in range(1, 100+1): # Section 5.
        if g['ptext'][k] != 0:
            g['obj'] += 1
    for k in range(1, g['tabndx']+1): # Section 4.
        if g['ktab'][k]//1000 == 2:
            verb = g['ktab'][k] - 2000
    for j in range(g['rtxsiz'], 0, -1): # Section 6.
        if g['rtext'][j] != 0:
            break
    for i in range(g['magsiz'], 0, -1): # Section 12.
        if g['mtext'][i] != 0:
            break

    if False:
        k = 100
        print(' TABLE SPACE USED:')
        print(' %6d OF %6d WORDS OF MESSAGES' % (g['linbytes']//5, g['linsiz']))
        print(' %6d OF %6d TRAVEL OPTIONS' % (g['trvs'], g['trvsiz']))
        print(' %6d OF %6d VOCABULARY WORDS' % (g['tabndx'], g['tabsiz']))
        print(' %6d OF %6d LOCATIONS' % (kk, g['locsiz']))
        print(' %6d OF %6d OBJECTS' % (g['obj'], k))
        print(' %6d OF %6d ACTION VERBS' % (verb, g['vrbsiz']))
        print(' %6d OF %6d RTEXT MESSAGES' % (j, g['rtxsiz']))
        print(' %6d OF %6d CLASS MESSAGES' % (g['clsses'], g['clsmax']))
        print(' %6d OF %6d HINTS' % (g['hntmax'], g['hntsiz']))
        print(' %6d OF %6d MAGIC MESSAGES' % (i, g['magsiz']))

    # Finally, since we're clearly setting things up for the first time...
    wizcom = poof()

def poof():
    '''
    As part of database initialisation, we call poof to set up some dummy
    prime-time specs, magic words, etc.
    '''

    d = {
        'hbegin':0,
        'hend':-1,
        'hname':'',
        'holid':0,
        'latncy':90,
        'magic':'DWARF',
        'magnm':11111, # Not used with passwd challenge removed. - mm
        'motd':'',
        'short':30,
        'wkday':0x3ff00, # 0o00777400
        'wkend':0,
    }
    try:
        with open('hours') as file:
            for line in file:
                line = line.strip()
                if line == '':
                    continue
                sp = line.find(' ')
                firstWord = line[:sp]
                if firstWord in ['hname','motd']:
                    d[firstWord] = line[1+sp:] # Might contain spaces.
                else:
                    line = line.split()
                    if len(line) != 2:
                        continue
                    var,val = line
                    if var == 'magic':
                        d[var] = val
                    else:
                        d[var] = int(val)
    except FileNotFoundError:
        pass
    return d

def pour(spk):
    #  POUR.  If no object, or object is bottle, assume contents of bottle.
    #  Special tests for pouring water or oil on plant or rusty door.

    if g['obj'] == w['bottle'] or g['obj'] == 0:
        g['obj'] = liq()
    if g['obj'] == 0:
        return what()
    if not toting(g['obj']):
        return {'fn':'newTurn', 'spk':spk}
    spk = 78 # YOU CAN'T POUR THAT.
    if g['obj'] != w['oil'] and g['obj'] != w['water']:
        return {'fn':'newTurn', 'spk':spk}
    g['prop'][w['bottle']] = 1
    g['place'][g['obj']] = 0
    spk = 77 # YOUR BOTTLE IS EMPTY AND THE GROUND IS WET.
    if not (at(w['plant']) or at(w['door'])):
        return {'fn':'newTurn', 'spk':spk}

    if not at(w['door']):
        spk = 112 # THE PLANT INDIGNANTLY SHAKES THE OIL OFF ITS LEAVES...
        if g['obj'] != w['water']:
            return {'fn':'newTurn', 'spk':spk}
        pspeak(w['plant'], g['prop'][w['plant']] + 1)
        g['prop'][w['plant']] = (g['prop'][w['plant']] + 2)%6
        g['prop'][w['plant2']] = g['prop'][w['plant']]//2
        k = w['null']
        return {'fn':'newLocation','goto':8, 'verb':k, 'kk':-1}
    g['prop'][w['door']] = 0
    if g['obj'] == w['oil']:
        g['prop'][w['door']] = 1
    spk = 113 + g['prop'][w['door']]
    return {'fn':'newTurn', 'spk':spk}

def put(obj,where,pval):
    '''
    Put is the same as move, except it returns a value used to set up the
    negated prop values for the repository objects.
    '''
    move(obj, where)
    return -1 - pval

def quitGame(verify=True):
    # QUIT.  Intransitive only.  Verify intent and exit if that's what he
    # wants.
    global w

    if verify:
        c['gaveup'] = yes(22,54,54) # DO YOU REALLY WANT TO QUIT NOW?
    if c['gaveup']:
        finish()
    return {'fn':'newTurn', 'spk':0}

def ran(rnge): # Unused.

    '''
    Since the ran function in lib40 seems to be a real lose, we'll use one of
    our own.  It's been run through many of the tests in Knuth Vol. 2 and
    seems to be quite reliable.  Ran returns a value uniformly selected
    between 0 and rnge-1.  Note resemblance to alg used in wizard.
    '''

    r = 0 # r/0/

    d = 1
    if r == 0:
        d,t = datime()
        r = 18*t + 5
        d = 1000 + d%1000
    for t in rnge(d):
        r = r*1021%0x100000
    return (rnge*r)//0x100000

def read(spk, intransitive=True):
    #  READ.  Magazines in dwarvish, message we've seen, and . . . oyster?
    global c, g, w

    if intransitive: # Find object.
        if here(w['magzin']):
            g['obj'] = w['magzin']
        if here(w['tablet']):
            g['obj'] = g['obj']*100 + w['tablet']
        if here(w['messag']):
            g['obj'] = g['obj']*100 + w['messag']
        if c['closed'] and toting(w['oyster']):
            g['obj'] = w['oyster']
        if g['obj'] > 100 or g['obj'] == 0 or dark():
            return what()

    obj = g['obj']
    if dark():
        s = (g['wd1'].strip() + g['wd1x'].strip()).upper()
        print(' I SEE NO %s HERE.' % s)
    if obj == w['magzin']:
        spk = 190 # MAGAZINE IS WRITTEN IN DWARVISH.
    if obj == w['tablet']:
        spk = 196 # "CONGRATULATIONS ON BRINGING LIGHT INTO THE DARK-ROOM!"
    if obj == w['messag']:
        spk = 191 # "NOT MAZE WHERE PIRATE LEAVES TREASURE CHEST."
    if obj == w['oyster'] and g['hinted'][2] and toting(w['oyster']):
        spk = 194 # IT SAYS THE SAME THING IT DID BEFORE.
    if (obj != w['oyster'] or g['hinted'][2]
        or not toting(w['oyster']) or not c['closed']):
        return {'fn':'newTurn', 'spk':spk}
    g['hinted'][2] = yes(192,193,54) # READ IT.  READ IT ANYWAY?
    return {'fn':'newTurn', 'spk':0}

def rub():
    # RUB.  Yields various snide remarks.
    global g

    if g['obj'] != w['lamp']:
        spk = 76 # PECULIAR.  NOTHING UNEXPECTED HAPPENS.
    return {'fn':'newTurn', 'spk':spk}

def say():
    #  SAY.  Echo wd2 (or wd1 if no wd2 (Say WHAT?, etc.).)  Magic words
    #  override.
    global g

    tk = g['wd2'].strip() + g['wd2x'].strip() + '".'
    if g['wd2'].strip() != '':
        g['wd1'] = g['wd2']
    i = vocab(g['wd1'], -1)
    # XYZZY, PLUGH, PLOVE, FEE, FIE, FOE, FOO, FUM
    if not (i in [62, 65, 71, 2025]): # Magic words.
        print('\n OKAY, "%s".' % g['wd1'])
        return {'fn':'newTurn', 'spk':0}
    g['wd2'] = ''
    g['obj'] = 0
    return analyseWord()

def score():
    # SCORE.  Go to scoring section, which will return to 8241 if scorng is
    # true.
    global w

    score,mxscor = finish(scorng=True)
    print('\n IF YOU WERE TO QUIT NOW, YOU WOULD SCORE%4d OUT OF A POSSIBLE%4d.'
        % (score,mxscor))
    c['gaveup'] = yes(143,54,54) # DO YOU INDEED WISH TO QUIT NOW?
    # quitGame(ask=False) # Might or might not quit.
    if c['gaveup']:
        finish()
    return {'fn':'newTurn', 'spk':0}

def secondWord():
    global g
    # Get second word for analysis.
    g['wd1'],g['wd1x'] = g['wd2'],g['wd2x']
    g['wd2'] = ''
    westOrW() # goto 2610
    return analyseWord()

def sections(db, sect):
    # Sections 1, 2, 6, 10, 12.  Read messages and set up pointers.
    global g

    oldloc = -1
    while True:
        line = db.readline().strip()
        if line[:2] == '-1': # End of section.
            return
        tab = line.find('\t')
        loc,msg = line[:tab],line[tab+1:] # Can't use split(), multiple tabs.
        loc = int(loc)
        g['linbytes'] += len(msg)
        if loc != oldloc: # New location.
            g['lines'].append(msg)
            g['linuse'] += 1
        else:
            g['lines'][g['linuse']] += '\n' + msg
        # Update pointers into lines[].
        match sect:
            case 1: # Long form descriptions.
                g['ltext'][loc] = g['linuse']
            case 2: # Short form descriptions.
                g['stext'][loc] = g['linuse']
            case 6: # Arbitrary messages.
                if loc > g['rtxsiz']:
                    bug(6) # Too many rtext or mtext messages.
                g['rtext'][loc] = g['linuse']
            case 10: # Class messages.
                g['ctext'][g['clsses']] = g['linuse']
                g['cval'][g['clsses']] = loc
                g['clsses'] += 1
            case 12: # Magic messages.
                if loc > g['magsiz']:
                    bug(6) # Too many rtext or mtext messages.
                g['mtext'][loc] = g['linuse']
        oldloc = loc
        if len(msg)+14 > g['linsiz']:
            bug(2) #  Too many words of messages.

def section3(db):
    '''
    The stuff for section 3 is encoded here.  Each "from-location" gets a
    contiguous section of the "travel" array.  Each entry in travel is
    newloc*1000 + keyword (from section 4, motion verbs), and is negated if
    this is the last entry for this location.  Key(n) is the index in travel
    of the first option at location n.

    Section 3: Travel Table.  Each line contains a location number (x), a second
    location number (y), and a list of motion numbers (see section 4).
    Each motion represents a verb which will go to y if currently at x.
    Y, in turn, is interpreted as follows.  Let m = y/1000, n = y mod 1000.
          If n<=300         It is the location to go to.
          If 300<n<=500     n-300 is used in a computed goto to
                            a section of special code.
          If n>500          Message n-500 from section 6 is printed,
                            and he stays wherever he is.
    Meanwhile, m specifies the conditions on the motion.
          If m=0            It's unconditional.
          If 0<m<100        It is done with m% probability.
          If m=100          Unconditional, but forbidden to dwarves.
          If 100<m<=200     He must be carrying object m-100.
          If 200<m<=300     Must be carrying or in same room as m-200.
          If 300<m<=400     Prop(m mod 100) must *not* be 0.
          If 400<m<=500     Prop(m mod 100) must *not* be 1.
          If 500<m<=600     Prop(m mod 100) must *not* be 2, etc.
    If the condition (if any) is not met, then the next *different*
    "destination" value is used (unless it fails to meet *its* conditions,
    in which case the next is found, etc.).  Typically, the next dest will
    be for one of the same verbs, so that its only use is as the alternate
    destination for those verbs.  For instance:
          15    110022      29    31    34    35    23    43
          15    14    29
    This says that, from loc 15, any of the verbs 29, 31, etc., will take
    him to 22 if he's carrying object 10, and otherwise will go to 14.
          11    303008      49
          11    9     50
    This says that, from 11, 49 takes him to 8 unless prop(3) = 0, in which
    case he goes to 9.  verb 50 takes him to 9 regardless of prop(3).
    '''

    global g

    while True:
        line = db.readline().strip()
        if line[:2] == '-1': # End of Section 3.
            return
        tk = list(map(int, line.split())) # Variable number of ints.
        loc,newloc = tk[0],tk[1]
        if g['key'][loc] == 0: # Unused location.
            g['key'][loc] = g['trvs'] # Where travel info on loc begins.
        else:
            g['travel'][g['trvs']-1] = -g['travel'][g['trvs']-1]
        for l in range(2,len(tk)):
            g['travel'][g['trvs']] = newloc*1000 + tk[l]
            g['trvs'] += 1
            if g['trvs'] == g['trvsiz']:
                bug(3) # Too many travel options.
        g['travel'][g['trvs']-1] = -g['travel'][g['trvs']-1]

def section4(db):
    '''
    Here we read in the vocabulary.  ktab(n) is the word number, atab(n) is
    the corresponding word.  The -1 at the end of section 4 is left in ktab
    as an end-marker.  The words are given a minimal hash to make reading the
    core-image harder.  Note that '/7-08' had better not be in the list, since
    it could hash to -1.

    Section 4: Vocabulary.  Each line contains a number (n), a tab, and a
       five-letter word.  Call m = n/1000.  If m = 0, then the word is a motion
       verb for use in travelling (see section 3).  Else, if m = 1, the word is
       an object.  Else, if m = 2, the word is an action verb (such as "carry"
       or "attack").  Else, if m = 3, the word is a special case verb (such as
       "dig") and n mod 1000 is an index into section 6.  Objects from 50 to
       (currently, anyway) 79 are considered treasures (for pirate, closeout).
    '''

    global g

    for g['tabndx'] in range(1, g['tabsiz']+1):
        val = db.readline().strip().split()
        g['ktab'][g['tabndx']] = int(val[0])
        if g['ktab'][g['tabndx']] == -1:
            g['atab'][g['tabndx']] = ''
            return
        g['atab'][g['tabndx']] = val[1][:5] # Ignore trailing comments on line.
        # Hash was to prevent search of compiled program for strings.
        # With python source available to user, why bother hashing!
        # p = np.array(list(map(ord, 'PHROG')))
        # w = np.array(list(map(ord, g['atab'][g['tabndx']])))
        # g['atab'][g['tabndx']] = xor(g['atab'][g['tabndx']], 'PHROG')
    bug(4) # Too many vocabulary words.

def section5(db):
    '''
    Section 5: object descriptions.  Each line contains a number (n), a tab,
       and a message.  If n is from 1 to 100, the message is the "inventory"
       message for object n.  Otherwise, n should be 000, 100, 200, etc., and
       the message should be the description of the preceding object when its
       prop value is n/100.  The n/100 is used only to distinguish multiple
       messages from multi-line messages; the prop info actually requires all
       messages for an object to be present and consecutive.  Properties which
       produce no message should be given the message ">$<".

    Data file lines:

        2	BRASS LANTERN
        000	THERE IS A SHINY BRASS LAMP NEARBY.
        100	THERE IS A LAMP SHINING NEARBY.

    are stored in lines[] as a single list:

        lines[i] = ['BRASS LANTERN', 'THERE IS A SHINY BRASS LAMP NEARBY.',
            'THERE IS A LAMP SHINING NEARBY.']

    where indices 1 and onward are assumed to be 000, 100, 200, ...
    '''

    global g

    oldloc = ''
    while True:
        line = db.readline().strip()
        if line[:2] == '-1': # End of section 5.
            break
        isInventory = (line[1:3] != '00')
        loc,msg = line.split('\t')
        loc = int(loc)
        g['linbytes'] += len(msg)
        if isInventory:
            i = g['linuse'] - 1
            g['lines'].append([msg]) # Inventory entry.
            g['linuse'] += 1
            g['ptext'][loc] = g['linuse']
        elif loc == oldloc:
            i = g['linuse']
            g['lines'][i][-1] += '\n' + msg # Inventory entry.
        else:
            g['lines'][g['linuse']].append(msg) # Entries 000, 100, 200, etc.
        if len(msg)+14 > g['linsiz']:
            bug(2) # Too many words of messages.
        oldloc = loc

def section7(db):
    '''
    Read in the initial locations for each object.  Also the immovability info.
    Plac contains initial locations of objects.  Fixd is -1 for immovable
    objects (including the snake), or = second loc for two-placed objects.

    Section 7: Object locations.  Each line contains an object number and its
       initial location (zero (or omitted) if none).  If the object is
       immovable, the location is followed by a "-1".  If it has two locations
       (e.g. the grate) the first location is followed with the second, and
       the object is assumed to be immovable.
    '''

    global g

    while True:
        v = list(map(int, db.readline().strip().split()))
        if v[0] == -1:
            return
        obj = v[0]
        if len(v) >= 2: g['plac'][obj] = v[1]
        if len(v) == 3: g['fixd'][obj] = v[2]

def section8(db):
    '''
    Read default message numbers for action verbs, store in actspk.

    Section 8: action defaults.  Each line contains an "action-verb" number and
       the index (in section 6) of the default message for the verb.
    '''

    global g

    while True:
        vals = list(map(int, db.readline().strip().split()))
        verb = vals[0]
        if verb == -1:
            return
        g['actspk'][verb] = vals[1]

def section9(db):
    '''
    Read info about available liquids and other conditions, store in cond.

    Section 9: Liquid assets, etc.  Each line contains a number (n) and up to 20
    location numbers.  Bit n (where 0 is the units bit) is set in cond[loc]
    for each loc given.  The cond bits currently assigned are:
          0     Light
          1     If bit 2 is on: on for oil, off for water
          2     Liquid asset, see bit 1
          3     Pirate doesn't go here unless following player
    Other bits are used to indicate areas of interest to "hint" routines:
          4     Trying to get into cave
          5     Trying to catch bird
          6     Trying to deal with snake
          7     Lost in maze
          8     Pondering dark room
          9     At Witt's End
    cond[loc] is set to 2, overriding all other bits, if loc has forced
    motion.
    '''

    global g

    while True:
        line = db.readline().strip()
        tk = list(map(int, line.split())) # Variable number of ints.
        k = tk[0]
        if k == -1:
            break
        for i in range(1, len(tk)):
            loc = tk[i]
            if bitset(loc,k):
                bug(8) # Location has cond bit being set twice.
            g['cond'][loc] |= 1<<k

def section11(db):
    '''
    Read data for hints.

    Section 11: hints.  Each line contains a hint number (corresponding to a
       cond bit, see section 9), the number of turns he must be at the right
       loc(s) before triggering the hint, the points deducted for taking the
       hint, the message number (section 6) of the question, and the message
       number of the hint.  These values are stashed in the "hints" array.
       Hntmax is set to the max hint number (<= hntsiz).  Numbers 1-3 are
       unusable since cond bits are otherwise assigned, so 2 is used to
       remember if he's read the clue in the repository, and 3 is used to
       remember whether he asked for instructions (gets more turns, but loses
       points).
    '''

    global g

    g['hntmax'] = 0
    while True:
        v = list(map(int, db.readline().strip().split()))
        if v[0] == -1:
            return
        if not (0 <= v[0] <= g['hntsiz']):
            bug(7) # Too many hints.
        g['hints'][v[0]][1:4+1] = v[1:]
        g['hntmax'] = max(g['hntmax'], v[0])

def stateRead(fname='state.adv'):
    '''Doing this brute force rather than pickle or similar so that it can be
    ported with ease to micropython for calculators, in particular.
    '''

    global c, g

    #   F i n d   g a m e   t o   l o a d
    files = os.listdir()
    afiles = []
    for f in files:
        if f[-4:] == '.adv':
            afiles.append(f)
    if len(afiles) == 0:
        print(' I SEE NO SAVED GAME HERE.')
        return
    elif len(afiles) == 1:
        fname = afiles[0] # One saved game, no need to ask user.
    elif len(afiles) > 1:
        print(' I SEE THESE SAVED GAMES:')
        for i,s in enumerate(afiles):
            print(' %d. %s' % (i+1,s))
        n = (inputCheck(' ENTER NUMBER OF GAME TO RESUME: ', dtype=int))
        n -= 1
        fname = afiles[n]

    #   L o a d   g a m e
    f = open(fname, 'r')
    while True:
        line = f.readline().strip()
        if line == '': #EOF
            break
        line = line.strip()
        if line == 'cave':
            d = c
            continue
        elif line == 'game':
            d = g
            continue
        var,val,tStr = line.split()
        val = val.split(',')
        if len(val) == 0:
            continue
        elif len(val) == 1:
            v = val[0]
            if   tStr == 'str':  d[var] = v
            elif tStr == 'int':  d[var] = int(v)
            elif tStr == 'bool': d[var] = (v == 'True')
        else: # List.
            res = []
            for v in val:
                if   tStr == 'str':  res.append(v)
                elif tStr == 'int':  res.append(int(v))
                elif tStr == 'bool': res.append(v == 'True')
            d[var] = res
    f.close()
    return

def stateWrite(fname='state.adv'):
    # Write dictionaries.
    f = open(fname, 'w')
    print('cave', file=f)
    for k in c.keys(): # Cave state.
        t = str(type(c[k]))
        t = t[:t.rfind("'")]
        t = t[t.find("'")+1:]
        print('%s %s %s' % (k, str(c[k]), t), file=f)
    print('game', file=f)
    for k in g.keys(): # Game state.
        if k in ['actspk','atab','cond','ctext','cval','fixd', 'hints',
            'key','ktab','lines','ltext','mtext','plac', 'ptext',
            'rtext','stext','travel']:
            continue # Won't change so reread at restart.
        if k[:2] == 'wd':
            continue
        t = str(type(g[k]))
        t = t[:t.rfind("'")]
        t = t[t.find("'")+1:]
        if t == 'list':
            t = str(type(g[k][0]))
            t = t[:t.rfind("'")]
            t = t[t.find("'")+1:]
            l = str(g[k])
            l = l.replace('[','')
            l = l.replace(']','')
            l = l.replace(' ','')
            print('%s %s %s' % (k, l, t), file=f)
        else:
            print('%s %s %s' % (k, str(g[k]), t), file=f)
    f.close()
    print(' GAME SAVED.')
    return

def suspend(restart=False):
    # SUSPEND.  Offer to exit leaving things restartable, but requiring a
    # delay before restarting (so can't save the world before trying
    # something risky).  Upon restarting, setup = -1 causes return to 8305 to
    # pick up again.

    global c, g, wizcom

    if restart:
        dbRead()
        stateRead()
        c['yea'] = start() # Line 8305
        g['setup'] = 3
        k = w['null']
        return {'fn':'newLocation','goto':8, 'verb':k, 'kk':-1}
    else:
        if c['demo']:
            spk = 201 # NO POINT IN SUSPENDING A DEMONSTRATION GAME.
            return {'fn':'newTurn', 'spk':spk}
        s = '\n I CAN SUSPEND YOUR ADVENTURE FOR YOU SO THAT YOU CAN'
        s += (' RESUME LATER, BUT\n YOU WILL HAVE TO WAIT AT LEAST%3d'
            % wizcom['latncy'])
        s += ' MINUTES BEFORE CONTINUING.'
        print(s)
        if not yes(200,54,54): # IS THIS ACCEPTABLE?
            return {'fn':'newTurn', 'spk':0}
        fname = input(' FILE NAME? (NULL TO USE "state.adv") ').strip()
        if fname == '':
            fname = 'state.adv'
        else:
            if fname.find('.adv') == -1:
                fname += '.adv'
        c['saved'],c['savet'] = datime()
        g['setup'] = -1
        stateWrite(fname)
        ciao()

def take(intransitive=True, spk=0):
    # Carry an object.  Special cases for bird and cage (if bird in cage, can't
    # take one without the other).  Liquids also special, since they depend on
    # status of bottle.  Also various side effects, etc.

    if intransitive:
        # Carry, no object given yet.  Ok if only one object present.
        if g['atloc'][g['loc']] == 0 or g['link'][g['atloc'][g['loc']]] != 0:
            return what()
        for i in range(1, 5+1):
            if g['dloc'][i] == g['loc'] and c['dflag'] >= 2:
                # Dwarf here & have met a dwarf.
                return what()
        g['obj'] = g['atloc'][g['loc']]

    if toting(g['obj']):
        return {'fn':'newTurn', 'spk':spk}
    spk = 25 # YOU CAN'T BE SERIOUS!
    if g['obj'] == w['plant'] and g['prop'][w['plant']] <= 0:
        spk = 115 # PLANT CANNOT BE PULLED FREE.
    if g['obj'] == w['bear'] and g['prop'][w['bear']] == 1:
        spk = 169 # BEAR IS STILL CHAINED TO THE WALL.
    if g['obj'] == w['chain'] and g['prop'][w['bear']] != 0:
        spk = 170 # THE CHAIN IS STILL LOCKED.
    if g['fixed'][g['obj']] != 0:
        return {'fn':'newTurn', 'spk':spk}
    if g['obj'] in [w['water'], w['oil']]:
        if not (here(w['bottle']) and liq() == g['obj']):
            g['obj'] = w['bottle']
            if toting(w['bottle']) and g['prop'][w['bottle']] == 1: # Empty.
                fill(spk)
            if g['prop'][w['bottle']] != 1:
                spk = 105 # YOUR BOTTLE IS ALREADY FULL.
            if not toting(w['bottle']):
                spk = 104 # YOU HAVE NOTHING IN WHICH TO CARRY IT.
            return {'fn':'newTurn', 'spk':spk}
        g['obj'] = w['bottle']
    if c['holdng'] >= 7:
        rspeak(92) # YOU CAN'T CARRY ANYTHING MORE
        return {'fn':'newTurn', 'spk':0}
    if g['obj'] == w['bird'] and g['prop'][w['bird']] == 0:
        if toting(w['rod']):
            rspeak(26) # THE BIRD WAS UNAFRAID...
            return {'fn':'newTurn', 'spk':0}
        if not toting(w['cage']):
            rspeak(27) # YOU CAN CATCH THE BIRD, BUT YOU CANNOT CARRY IT.
            return {'fn':'newTurn', 'spk':0}
        g['prop'][w['bird']] = 1
    if ((g['obj'] == w['bird'] or g['obj'] == w['cage'])
        and g['prop'][w['bird']] != 0):
        carry(w['bird']+w['cage']-g['obj'], g['loc'])
    carry(g['obj'], g['loc']) # The typical case!
    k = liq()
    if g['obj'] == w['bottle'] and k != 0: # k==0 no liquid here.
        g['place'][k] = -1
    return {'fn':'newTurn', 'spk':54}

def throw(spk):
    # THROW.  Same as discard unless axe.  Then same as attack except ignore
    # bird, and if dwarf is present then one might be killed.  (Only way to
    # do so!) Axe also special for dragon, bear, and troll.  Treasures
    # special for troll.
    #
    # Synonyms: THROW, TOSS.

    global g

    if toting(w['rod2']) and g['obj'] == w['rod'] and not toting(w['rod']):
        g['obj'] = w['rod2']
    if not toting(g['obj']):
        return {'fn':'newTurn', 'spk':spk}
    # Next line asks, if not throwing treasure at troll...
    if not (g['obj'] >= 50 and g['obj'] <= g['maxtrs'] and at(w['troll'])):
        if g['obj'] == w['food'] and here(w['bear']):
            # But throwing food is another story.
            g['obj'] = w['bear']
            return feed(spk)
        if g['obj'] != w['axe']:
            return discard(spk)
        for i in range(1, 5+1):
            # Needn't check dflag if axe is here.
            if g['dloc'][i] == g['loc']:
                break
        else:
            spk = 152 # AXE BOUNCES OFF DRAGON'S THICK SCALES
            if at(w['dragon']) and g['prop'][w['dragon']] == 0:
                rspeak(spk)
                drop(w['axe'],g['loc'])
                k = w['null']
                return {'fn':'newLocation', 'goto':8, 'verb':k, 'kk':-1}
            spk = 158 # TROLL DEFTLY CATCHES THE AXE...
            if at(w['troll']):
                rspeak(spk)
                drop(w['axe'],g['loc'])
                k = w['null']
                return {'fn':'newLocation', 'goto':8, 'verb':k, 'kk':-1}
            if here(w['bear']) and g['prop'][w['bear']] == 0:
                # This'll teach him to throw the axe at the bear!
                spk = 164 # AXE MISSES...
                drop(w['axe'],g['loc'])
                g['fixed'][w['axe']] = -1
                g['prop'][w['axe']] = 1
                juggle(w['bear'])
                return {'fn':'newTurn', 'spk':spk}
            g['obj'] = 0
            attack(spk)
        spk = 48 # DWARF DODGES OUT OF THE WAY.
        # If saved not = -1, he bypassed the "start" call.
        if not (randint(3) == 0 or c['saved'] != -1): # 1/3 kill rate.
            g['dseen'][i] = False
            g['dloc'][i] = 0 # Kill dwarf.
            spk = 47 # YOU KILLED A LITTLE DWARF.
            c['dkill'] += 1
            if c['dkill'] == 1:
                spk = 149 # YOU KILLED A LITTLE DWARF...BLACK SMOKE.
        rspeak(spk)
        drop(w['axe'],g['loc'])
        k = w['null']
        return {'fn':'newLocation', 'goto':8, 'verb':k, 'kk':-1}
    spk = 159 # TROLL CATCHES TREASURE, SCURRIES OUT OF SIGHT
    # Snarf a treasure for the troll.
    drop(g['obj'], 0)
    move(w['troll'], 0)
    move(w['troll']+100, 0)
    drop(w['troll2'], g['plac'][w['troll']])
    drop(w['troll2']+100, g['fixd'][w['troll']])
    juggle(w['chasm'])
    return {'fn':'newTurn', 'spk':spk}

def transitive(spk=54):
    # Analyse a transitive verb.
    # Line 4090

    verb = g['verb']
    match verb:
        case  1: return take(False, spk)   # TAKE
        case  2: return discard(spk)       # DROP
        case  3: return say()              # SAY
        case  4: return locking(False)     # OPEN
        case  5: return newTurn(verb)      # NOTH
        case  6: return locking(False)     # LOCK
        case  7: return lampOn(spk)        # ON
        case  8: return lampOff(spk)       # OFF
        case  9: return wave(spk)          # WAVE
        case 10: return newTurn(verb, spk) # CALM
        case 11: return newTurn(verb, spk) # WALK
        case 12: return attack(spk)        # KILL
        case 13: return pour(spk)          # POUR
        case 14: return eat(spk, False)    # EAT
        case 15: return drink(spk)         # DRNK
        case 16: return rub()              # RUB
        case 17: return throw(spk)         # TOSS
        case 18: return newTurn(verb, spk) # QUIT
        case 19: return find(spk, verb)    # FIND
        case 20: return find(spk, verb)    # INVN
        case 21: return feed(spk)          # FEED
        case 22: return fill(spk)          # FILL
        case 23: return blast(spk)         # BLST
        case 24: return newTurn(verb, spk) # SCOR
        case 25: return newTurn(verb, spk) # FOO
        case 26: return newTurn(verb, spk) # BRF
        case 27: return read(spk, False)   # READ
        case 28: return breakObj(spk)      # BREK
        case 28: return wakeDwarves(spk)   # WAKE
        case 29: return newTurn(verb, spk) # SUSP
        case 20: return newTurn(verb, spk) # HOUR
        case _: bug(24) # Transitive action verb exceeds goto list.

def vocab(ida, init):

    '''
    Look up id in the vocabulary (atab) and return its "definition" (ktab),
    or -1 if not found.  If init is positive, this is an initialisation call
    setting up a keyword variable, and not finding it constitutes a bug.  It
    also means that only ktab values which taken over 1000 equal init may be
    considered.  (Thus "steps", which is a motion verb as well as an object,
    may be located as an object.)  And it also means the ktab value is taken
    mod 1000.
    '''

    global ktab, atab, tabsiz

    # hash=ida.xor.'PHROG' # No need to hide words in core image.
    for i in range(1, g['tabsiz']+1):
        if g['ktab'][i] == -1:
            v = -1
            if init < 0:
                return v
            bug(5) # Required vocabulary word not found.
        if init >= 0 and g['ktab'][i]//1000 != init:
            continue
        if g['atab'][i] == ida : #if atab[i] == hash:
            v = g['ktab'][i]
            if init >= 0:
                v = v%1000
            return v
    bug(21)

def wizard():
    '''
    Ask if he's a wizard.  If he says yes, make him prove it.  Return true if
    he really is a wizard.
    '''

    global wizcom

    wizard = yesm(16,0,7) # if not 'WIZARD?' then 'VERY WELL.'
    if not wizard:
        return False

    #  He says he is.  First step: does he know anything magical?

    mspeak(17) # PROVE IT!  SAY THE MAGIC WORD!
    word,_,_,_ = getin()
    if word != wizcom['magic']: # Is it 'DWARF'?
        #  Aha!  An impostor!
        mspeak(20) # FOO, YOU ARE NOTHING BUT A CHARLATAN!
        return False 

    if yesm(18,0,0): # KNOW WHAT I THOUGHT IT WAS?
        #  Aha!  An impostor!
        mspeak(20) # FOO, YOU ARE NOTHING BUT A CHARLATAN!
        return False 
    # Let's skip the challenge-reply. :-)
    print(' AH, EM, IT HAS SLIPPED MY MIND.')

    #  By George, he really *is* a wizard!
    mspeak(19) # OH DEAR, YOU REALLY *ARE* A WIZARD!
    return True

def wakeDwarves(spk):
    # WAKE.  Only use is to disturb the dwarves.

    global c, g

    if g['obj'] != w['dwarf'] or not c['closed']:
        return {'fn':'newTurn', 'spk':spk}
    rspeak(199) # NEAREST DWARF WAKES UP GRUMPILY...
    dwarvesDisturbed()

def wave(spk):
    # WAVE.  No effect unless waving rod at fissure.

    if not toting(g['obj']) or (g['obj'] == w['rod'] and toting(w['rod2'])):
        spk = 29 # YOU AREN'T CARRYING IT!
    if (g['obj'] != w['rod'] or not at(w['fissur'])
        or not toting(g['obj']) or c['closng']):
        return {'fn':'newTurn', 'spk':spk}
    g['prop'][w['fissur']] = 1 - g['prop'][w['fissur']]
    pspeak(w['fissur'], 2-g['prop'][w['fissur']])
    return {'fn':'newTurn', 'spk':0}

def what():

    # Random intransitive verbs come here.  Clear obj just in case (see
    # "attack").

    # Line 8000
    # w = a5toa1(wd1,wd1x,'WHAT?')
    #print('\n %s' % w)
    print(' ' + g['wd1'].strip() + g['wd1x'].strip() + ' WHAT?')
    g['obj'] = 0
    return {'fn':'newTurn', 'spk':-1}

def mspeak(i, nl=True):

    '''
    Print the i-th "magic" message (Section 12 of database).
    '''
    global g
    if i != 0:
        speak(g['mtext'][i], nl=nl)

def pspeak(msg, skip):

    '''
    Find the skip+1st message from msg and print it.  Msg should be the index
    of the inventory message for object.  (inven+n+1 message is prop=n
    message).
    '''

    global g
    speak(g['ptext'][msg], 1+skip)

def rspeak(i):
    '''
    Print the i-th "random" message (Section 6 of database).
    '''
    global g
    if i != 0:
        speak(g['rtext'][i])

def shift(val,dist):
    #  return val left-shifted (logically) dist bits (right-shift if dist<0).

    if   dist  < 0: return val >> -dist
    elif dist == 0: return val
    else:           return val << dist

def speak(n, propMsg=-1, nl=True):
    '''
    Print the message which starts at lines(n).  Precede it with a blank line
    unless blklin is false.
    '''

    global g

    if n == 0:
        return
    msg = g['lines'][n]
    if propMsg != -1:
        msg = msg[propMsg] # Section 5 only.
    if msg[:3] == '>$<': # Don't print anything.
        return
    if g['blklin']:
        print('')
    msg = msg.replace('\n', '\n ')
    if nl:
        print(' %s' % msg)
    else:
        print(' %s' % msg, end='')

def start():
    '''
    Check to see if this is "prime time".  If so, only wizards may play,
    though others may be allowed a short game for demonstration purposes.  If
    setup<0, we're continuing from a saved game, so check for suitable
    latency.  Return true if this is a demo game (value is ignored for
    restarts).
    '''

    global wizcom

    #  First find out whether it is prime time (save in ptime) and, if
    #  restarting, whether it's too soon (save in soon).  Prime-time specs
    #  are in wkday, wkend, and holid; see maint routine for details.  Latncy
    #  is required delay before restarting.  Wizards may cut this to a
    #  third.

    d,t = datime()
    primtm = wizcom['wkday']
    if d%7 <= 1: # 0,1 are Sat,Sun.
        primtm = wizcom['wkend']
    if wizcom['hbegin'] <= d <= wizcom['hend']: # During a holiday.
        primtm = wizcom['holid']
    ptime = (primtm & (1<<(t//60))) != 0
    soon = False 
    if g['setup'] < 0:
        delay = (d-c['saved'])*1440 + (t-c['savet'])
        if delay < wizcom['latncy']:
            print(' THIS ADVENTURE WAS SUSPENDED A MERE %3d MINUTES AGO.'
                % delay)
            soon = True 
            if delay < wizcom['latncy']//3:
                mspeak(2) # EVEN WIZARDS HAVE TO WAIT LONGER THAN THAT!
                sys.exit(0)
    # If neither too soon nor prime time, no problem.  Else specify what's
    # wrong.
    start = False 
    if not soon:
        if not ptime:
            c['saved'] = -1
            return start
        # Come here if not restarting too soon (maybe not restarting at all),
        # but it's prime time.  Give our hours and see if he's a wizard.  If
        # not, then can't restart, but if just beginning then we can offer a
        # short game.
        mspeak(3) # COLOSSAL CAVE IS CLOSED.
        hours()
        mspeak(4) # ONLY WIZARDS NOW
        if wizard():
            c['saved'] = -1
            return start
        if g['setup'] < 0:
            mspeak(9) # RESUME YOUR ADVENTURE LATER
            sys.exit(0)
        start = yesm(5,7,7) # WE ALLOW VISITORS TO MAKE SHORT EXPLORATIONS
        if start:
            c['saved'] = -1
            return start
        sys.exit(0)
    # Come here if restarting too soon.  If he's a wizard, let him go
    # (and note that it then doesn't matter whether it's prime time).
    # else, tough beans.
    mspeak(8) # ONLY A WIZARD THIS SOON
    if wizard():
        c['saved'] = -1
        return start
    mspeak(9) # RESUME YOUR ADVENTURE LATER
    sys.exit(0)

def westOrW():
    global c, g

    if g['wd1'] == 'WEST':
        c['iwest'] += 1
        if c['iwest'] == 10:
            rspeak(17) # IF YOU PREFER, SIMPLY TYPE W RATHER THAN WEST.

def yes(x,y,z):
    ''' Call yesx (below) with messages from Section 6.
    '''
    return yesx(x,y,z,rspeak)

def yesm(x,y,z):
    ''' Call yesx (below) with messages from Section 12.
    '''
    return yesx(x,y,z,mspeak)

def yesx(x,y,z,spk):
    '''
    Print message x, wait for yes/no answer.  If yes, print y and leave yea
    true; if no, print z and leave yea false.  Spk is either rspeak or mspeak.
    '''

    while True:
        if x != 0:
            spk(x)
        reply,_,_,_ = getin()
        if reply in ['YES', 'Y', 'NO', 'N']:
            break
        print('\n PLEASE ANSWER THE QUESTION.')

    if reply == 'YES' or reply == 'Y':
        yesx = True 
        if y != 0:
            spk(y)
    else:
        yesx = False 
        if z != 0:
            spk(z)
    return yesx

if __name__ == '__main__':
    main()

