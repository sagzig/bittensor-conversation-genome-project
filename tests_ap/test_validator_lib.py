import pytest
import random

from conversationgenome.ConfigLib import c
from conversationgenome.Utils import Utils

from conversationgenome.ValidatorLib import ValidatorLib
from conversationgenome.validator.evaluator import Evaluator
from conversationgenome.WandbLib import WandbLib

class MockAxon:
    uuid = "a"
    hotkey = ""


class MockResponse:
    responses = {}
    responses = {}
    cgp_output = None
    axon = None

    def __init__(self):
        self.axon = MockAxon()



@pytest.mark.asyncio
async def test_full():
    wl = WandbLib()
    await wl.init_wandb()
    # Config variables
    c.set('system', 'mode', 'test')
    miner_uids = [1,2,3,4,5,6,7,8,9]
    vl = ValidatorLib()
    el = Evaluator()
    await wl.log_example_data("ABC")
    result = await vl.reserve_conversation()
    test_mode = True
    if result:
        # LOG: conversation id, num_lines, num_participants, convo windows values
        #
        miners_per_window = c.get("validator", "miners_per_window", 3)
        (full_conversation, full_conversation_metadata, conversation_windows) = result
        if c.get("env", "LLM_TYPE") == "spacy":
            print("SPACY TEST MODE")
            # In test_mode, to expand the miner scores, remove half of the full convo tags.
            # This "generates" more unique tags found for the miners
            half = int(len(full_conversation_metadata['tags'])/2)
            full_conversation_metadata['tags'] = full_conversation_metadata['tags'][0:half]
        conversation_guid = Utils.get(full_conversation, "uid")
        #await vl.send_windows_to_miners(conversation_windows, full_conversation=full_conversation, full_conversation_metadata=full_conversation_metadata)
        # Loop through conversation windows. Send each window to multiple miners
        print(f"Found {len(conversation_windows)} conversation windows. Sequentially sending to batches of miners")

        for window_idx, conversation_window in enumerate(conversation_windows):
            print(f"conversation_window {window_idx}", conversation_window)
            selected_miner_uids = vl.selectStage1Miners(miner_uids)
            print("Selected miners", selected_miner_uids)

            miner_results = await vl.send_to_miners(conversation_guid, window_idx, conversation_window, selected_miner_uids)
            mock_miner_responses = []
            for idx, miner_result in enumerate(miner_results):
                print(f"RESULT uid: {miner_result['uid']}, tags: {miner_result['tags']} vector count: {len(miner_result['vectors'])}")
                response = MockResponse()
                response.axon.hotkey = "HK-"+str(idx)
                response.axon.uuid = str(miner_result['uid'])
                response.cgp_output = [miner_result]

                mock_miner_responses.append(response)
            # Log seperate rows for each miner
            # Summary log


            # Evaluate results of miners
            scores = await el.evaluate(full_conversation_metadata, mock_miner_responses)
            print("SCORES", scores)
            break
    await wl.end_log_wandb("ABC")




    #await vl.neighborhood_test()
    #await vl.llm_test()


