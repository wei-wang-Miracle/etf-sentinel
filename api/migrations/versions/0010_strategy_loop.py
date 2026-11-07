"""当前持仓ETF研究批次、观察版本、逐日计划及人工执行关联。"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    """建立带中文注释的业务表，冻结结构而不依赖未来模型定义。"""
    op.execute(
        "CREATE TABLE strategy_research_batches (\n\tresearch_batch_id SERIAL NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tinput_snapshot JSON NOT NULL, \n\tresult_snapshot JSON NOT NULL, \n\tinput_sha256 VARCHAR(64) NOT NULL, \n\tPRIMARY KEY (research_batch_id)\n)"
    )
    op.execute(
        "COMMENT ON TABLE strategy_research_batches IS 'ETF策略研究批次；冻结持仓范围、开发验证区间、每只五万元假设与全部成功失败结果'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_research_batches.research_batch_id IS '本地研究批次唯一编号'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_research_batches.created_at IS '研究创建时间，带时区'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_research_batches.input_snapshot IS '冻结输入JSON：持仓代码及源日期、候选参数版本、每只50000元、成本、开发验证区间；非真实本金'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_research_batches.result_snapshot IS '冻结输出JSON：每只ETF及组合的各区间候选净值指标、实验编号、失败原因；缺失不补零'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_research_batches.input_sha256 IS '规范输入快照SHA256，核查研究假设未被修改'"
    )
    op.execute(
        "CREATE TABLE strategy_observations (\n\tobservation_id SERIAL NOT NULL, \n\tresearch_batch_id INTEGER NOT NULL, \n\tinstrument_code VARCHAR(6) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tactive BOOLEAN NOT NULL, \n\trule_snapshot JSON NOT NULL, \n\tPRIMARY KEY (observation_id), \n\tFOREIGN KEY(research_batch_id) REFERENCES strategy_research_batches (research_batch_id), \n\tFOREIGN KEY(instrument_code) REFERENCES instruments (instrument_code)\n)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_strategy_observation_active ON strategy_observations (instrument_code) WHERE active"
    )
    op.execute(
        "COMMENT ON TABLE strategy_observations IS 'ETF策略观察版本；采用规则不代表已下单或实际成交，修改规则需新建版本'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_observations.observation_id IS '观察版本唯一编号'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_observations.research_batch_id IS '规则来源研究批次编号'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_observations.instrument_code IS '可交易ETF六位代码，指数不得作为观察对象'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_observations.created_at IS '用户采用时间，带时区；此前历史不算前向业绩'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_observations.active IS '是否继续生成新计划；暂停不修改历史规则及信号'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_observations.rule_snapshot IS '不可变规则JSON：候选key、策略版本、参数、资金分配百分数、每只五万元及成本；不含真实账户本金'"
    )
    op.execute(
        "CREATE TABLE strategy_signals (\n\tsignal_id SERIAL NOT NULL, \n\tobservation_id INTEGER NOT NULL, \n\tinstrument_code VARCHAR(6) NOT NULL, \n\tgenerated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdata_cutoff DATE NOT NULL, \n\texecution_date DATE NOT NULL, \n\tplan_snapshot JSON NOT NULL, \n\tevidence_snapshot JSON NOT NULL, \n\tskip_note VARCHAR, \n\tskipped_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (signal_id), \n\tFOREIGN KEY(observation_id) REFERENCES strategy_observations (observation_id), \n\tFOREIGN KEY(instrument_code) REFERENCES instruments (instrument_code)\n)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_strategy_signal_observation_day ON strategy_signals (observation_id, execution_date)"
    )
    op.execute(
        "COMMENT ON TABLE strategy_signals IS 'ETF逐日观察计划与生成时证据；提示、人工确认和真实成交分开，不回填历史信号'"
    )
    op.execute("COMMENT ON COLUMN strategy_signals.signal_id IS '日计划唯一编号'")
    op.execute(
        "COMMENT ON COLUMN strategy_signals.observation_id IS '产生计划的不可变观察版本编号'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_signals.instrument_code IS '计划对应可交易ETF六位代码'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_signals.generated_at IS '首次生成时间，带时区；同版本同执行日重复请求不修改'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_signals.data_cutoff IS '决策所用完整行情最后交易日，不晚于生成时已采集数据'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_signals.execution_date IS '最早执行的尚未开盘交易日；不表示实际成交日'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_signals.plan_snapshot IS '冻结计划JSON：方向、研究目标比例份额、实际及可用份额、数据源日期、原因、因子、输入摘要和待资金核对提示'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_signals.evidence_snapshot IS '决策证据JSON：当时完整行情、权益、规则版本及采集时刻，可重算；不使用后来修订覆盖'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_signals.skip_note IS '用户明确不执行的原因；空表示未主动跳过，不等于未成交证明'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_signals.skipped_at IS '人工跳过确认时间，带时区；未跳过为空'"
    )
    op.execute(
        "CREATE TABLE strategy_execution_links (\n\texecution_link_id SERIAL NOT NULL, \n\tsignal_id INTEGER NOT NULL, \n\taccount_id INTEGER NOT NULL, \n\tcurr_date DATE NOT NULL, \n\tentrust_no VARCHAR(32) NOT NULL, \n\tconfirmed_trade_date DATE NOT NULL, \n\tconfirmed_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tconfirmed_amount NUMERIC(20, 4) NOT NULL, \n\tconfirmation_note VARCHAR NOT NULL, \n\tPRIMARY KEY (execution_link_id), \n\tFOREIGN KEY(account_id, curr_date, entrust_no) REFERENCES account_entrusts (account_id, curr_date, entrust_no), \n\tFOREIGN KEY(signal_id) REFERENCES strategy_signals (signal_id), \n\tFOREIGN KEY(account_id) REFERENCES accounts (account_id)\n)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_strategy_execution_entrust ON strategy_execution_links (account_id, curr_date, entrust_no)"
    )
    op.execute(
        "COMMENT ON TABLE strategy_execution_links IS '真实累计委托与计划的人工确认关联；一条委托最多归属一个计划，源数量修订后重新核对'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_execution_links.execution_link_id IS '执行关联唯一编号'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_execution_links.signal_id IS '人工确认对应的日计划编号'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_execution_links.account_id IS '本地账户编号，不是资金账号'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_execution_links.curr_date IS '源委托关联日期，与account_id及entrust_no共同定位累计委托'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_execution_links.entrust_no IS '源累计委托号；不代表逐笔成交编号'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_execution_links.confirmed_trade_date IS '用户依据对账资料确认的实际成交日期，必须等于计划执行日'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_execution_links.confirmed_at IS '人工关联确认时间，带时区；不当作成交时间'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_execution_links.confirmed_amount IS '确认时源累计成交份额快照，份；源后续变化用于展示修订差异'"
    )
    op.execute(
        "COMMENT ON COLUMN strategy_execution_links.confirmation_note IS '人工确认依据或偏离说明，不可空白；不包含自动下单含义'"
    )
    op.execute(
        "INSERT INTO jobs (job_id, schedule_enabled, scheduled_time) VALUES (5, true, '08:30')"
    )
    op.execute(
        "COMMENT ON COLUMN jobs.job_id IS '采集任务唯一编号；1为ETF日行情，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情，5为策略日计划'"
    )


def downgrade():
    """按依赖反序撤销本轮新增表及独立调度。"""
    op.execute("DELETE FROM runs WHERE job_id=5")
    op.execute("DELETE FROM jobs WHERE job_id=5")
    op.execute(
        "COMMENT ON COLUMN jobs.job_id IS '采集任务唯一编号；1为ETF日行情，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情'"
    )
    op.drop_table("strategy_execution_links")
    op.drop_table("strategy_signals")
    op.drop_table("strategy_observations")
    op.drop_table("strategy_research_batches")
