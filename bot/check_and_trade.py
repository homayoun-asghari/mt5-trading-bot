def check_and_trade(stop_event, news_df):
    # Initial scheduling
    schedule_job()
    
    while not stop_event.is_set():
        try:
            # Run scheduled tasks
            schedule.run_pending()
            
            # Print MT5 time
            MT5 = get_mt5_time()
            MT5 = datetime.strptime(MT5, '%Y-%m-%d %H:%M:%S')
            logging.info(f"Current MT5 time: {MT5}")
            
            # Get next bar time and check time
            next_bar_time = get_next_bar_time(mt5.TIMEFRAME_M15)
            next_check_time = next_bar_time + timedelta(seconds=1)
            logging.info(f"Next check time: {next_check_time}")

            # Filter news events for the current day
            current_date = MT5.strftime('%b %d')  # Format current date as "Sep 24"
            news_df['date'] = pd.to_datetime(news_df['date'], errors='coerce')
            news_df_today = news_df[news_df['date'].dt.strftime('%b %d') == current_date]

            #print(f"Current date: {current_date}")
            logging.info(f"News events for today:\n{news_df_today[['date', 'time', 'currency','impact','event']]}")
            logging.info(f"--------------------------------------")
                             
            # Wait until 3 seconds after the bar closes
            while MT5 < next_check_time:
                MT5 = get_mt5_time()
                MT5 = datetime.strptime(MT5, '%Y-%m-%d %H:%M:%S')
                time.sleep(1)  # Sleep briefly to avoid busy waiting

            # Check for upcoming news events
            for index, row in news_df_today.iterrows():
                news_time = datetime.strptime(row['time'], '%I:%M %p')  # Adjusted format to match '04:45 PM'
                news_time = news_time.replace(year=MT5.year, month=MT5.month, day=MT5.day)  # Ensure the correct date
                message_logged = False  # Flag to check if the message has already been logged

                while news_time - timedelta(minutes=29) <= MT5 < news_time + timedelta(minutes=15):
                    # Fetch open position
                    open_position = get_open_position()
                    
                    if open_position:
                        close_position(open_position)
                        logging.info("Closed open position due to upcoming news event.")
                    
                    if not message_logged:  # Log only if the message hasn't been logged yet
                        logging.info(f"News event at {news_time} and the news is {row['event']}. Halting trading.")
                        message_logged = True  # Set the flag to True after logging the message
                    
                    MT5 = get_mt5_time()
                    MT5 = datetime.strptime(MT5, '%Y-%m-%d %H:%M:%S')
                    time.sleep(1)
                

            # Fetch current signal and its time
            current_signal, signal_time, signal_prev, upper, mid, lower, atr, prob, kelly, stoch, stoch_k, stoch_d = get_signal('EURUSD_i')
            ticker = 'EURUSD_i'

            # Check if initial signal meets criteria
            if (current_signal == 1 and stoch == 0) or (current_signal == -1 and stoch == 0) or kelly <= 0:
                current_signal, signal_time, signal_prev, upper, mid, lower, atr, prob, kelly, stoch, stoch_k, stoch_d = get_signal('GBPUSD_i')
                ticker = 'GBPUSD_i'

                # Check again after switching to GBPUSD
                if (current_signal == 1 and stoch == 0) or (current_signal == -1 and stoch == 0) or kelly <= 0:
                    current_signal, signal_time, signal_prev, upper, mid, lower, atr, prob, kelly, stoch, stoch_k, stoch_d = get_signal('AUDUSD_i')
                    ticker = 'AUDUSD_i'

                    # Check again after switching to AUDUSD
                    if (current_signal == 1 and stoch == 0) or (current_signal == -1 and stoch == 0) or kelly <= 0:
                        current_signal, signal_time, signal_prev, upper, mid, lower, atr, prob, kelly, stoch, stoch_k, stoch_d = get_signal('USDJPY_i')
                        ticker = 'USDJPY_i'

            # Final check and logging
            if (current_signal == 1 and stoch == 1 and kelly > 0) or (current_signal == -1 and stoch == -1 and kelly > 0):
                logging.info(f"WE have new signal in {ticker}: {current_signal} and stoch is {stoch}, Signal time: {signal_time}, The probability: {prob} %")
            else:
                logging.info("WE don't have a new signal")

            # Fetch open position
            open_position = get_open_position()
            current_ticker = open_position.symbol

            # Check if the signal time is 30 minutes behind current MT5 time
            time_diff = MT5 - signal_time
            if time_diff > timedelta(minutes=30):
                logging.info("We do not have a new signal yet")
                if open_position:
                    close_position(open_position)
                continue  # Skip further processing

            if open_position:
                current_signal, signal_time, signal_prev, upper, mid, lower, atr, prob, kelly, stoch, stoch_k, stoch_d = get_signal(current_ticker)
                if (stoch_k > stoch_d and open_position.type == mt5.ORDER_TYPE_SELL) or \
                   (stoch_k < stoch_d and open_position.type == mt5.ORDER_TYPE_BUY):
                    logging.info(f"Stoch crossed over, closing position.")
                    close_position(open_position)
                    # After closing, wait to ensure the position is closed before opening a new one
                    time.sleep(0.1)
                    open_position = get_open_position()  # Re-fetch the open position status
                    if open_position is None:
                        if current_signal == 1 and stoch == 1 and kelly > 0:
                            entry = mt5.symbol_info_tick(ticker).ask
                            if entry < mid:
                                sl = lower - (1.3 * atr)
                                tp = mid
                            elif entry > mid:
                                sl = mid  - (1.3 * atr)
                                tp = upper
                            lot = calculate_lot_size(ticker, entry, sl)
                            execute_trade(ticker, current_signal, lot, sl, tp)
                        elif current_signal == -1 and stoch == -1 and kelly > 0:
                            entry = mt5.symbol_info_tick(ticker).bid
                            if entry < mid:
                                sl = mid  + (1.3 * atr)
                                tp = lower
                            elif entry > mid:
                                sl = upper + (1.3 * atr)
                                tp = mid
                            lot = calculate_lot_size(ticker, entry, sl)
                            execute_trade(ticker, current_signal, lot, sl, tp)
                        elif  kelly <= 0:
                            logging.info(f"Kelly is not favorable and it is {kelly}.")
                    else:
                        logging.info("Failed to close the position. Not executing new trade.")
                else:
                    logging.info(f"Position exists.")
                    # modify_open_position(upper, lower)
            else:
                if current_signal == 1 and stoch == 1 and  kelly > 0:
                    entry = mt5.symbol_info_tick(ticker).ask
                    if entry < mid:
                        sl = lower - (1.3 * atr)
                        tp = mid
                    elif entry > mid:
                        sl = mid - (1.3 * atr)
                        tp = upper
                    lot = calculate_lot_size(ticker, entry, sl)
                    execute_trade(ticker, current_signal, lot, sl)
                elif current_signal == -1 and stoch == -1 and kelly > 0:
                    entry = mt5.symbol_info_tick(ticker).bid
                    if entry < mid:
                        sl = mid + (1.3 * atr)
                        tp = lower
                    elif entry > mid:
                        sl = upper + (1.3 * atr)
                        tp = mid
                    lot = calculate_lot_size(ticker, entry, sl)
                    execute_trade(ticker, current_signal, lot, sl, tp)
                elif  kelly <= 0:
                    logging.info(f"Kelly is not favorable and it is {kelly}.")

        except Exception as e:
            logging.info(f"An error occurred: {e}")
            time.sleep(60)  # Wait before retrying in case of error














            # Fetch open position
            open_position = get_open_position()
            if open_position:
                current_ticker = open_position.symbol
                current_signal, signal_time, signal_prev, upper, mid, lower, atr, prob, kelly, stoch, stoch_k, stoch_d = get_signal(current_ticker)
                if (stoch_k > stoch_d and open_position.type == mt5.ORDER_TYPE_SELL) or \
                   (stoch_k < stoch_d and open_position.type == mt5.ORDER_TYPE_BUY):
                    logging.info(f"Stoch crossed over, closing position.")
                    close_position(open_position)
                else:
                    logging.info(f"We already have an open position")