-- ============================================================
-- Migration: Initial Schema
-- Database : PostgreSQL
-- Tables   : ordertransaction, orderdetail
-- ============================================================

-- ============================================================
-- TABLE: ordertransaction
-- ============================================================
CREATE TABLE IF NOT EXISTS ordertransaction (
    "TransactionID"             INTEGER         NOT NULL,
    "ShopID"                    INTEGER         NOT NULL DEFAULT 0,

    -- Receipt info
    "ReceiptYear"               SMALLINT        DEFAULT 0,
    "ReceiptMonth"              SMALLINT        DEFAULT 0,
    "ReceiptID"                 INTEGER         NOT NULL DEFAULT 0,
    "ReferenceNo"               VARCHAR(20)     DEFAULT NULL,
    "QueueName"                 VARCHAR(50)     DEFAULT NULL,

    -- Dates
    "SaleDate"                  DATE            DEFAULT NULL,
    "PaidTime"                  TIMESTAMP       DEFAULT NULL,
    "CloseTime"                 TIMESTAMP       DEFAULT NULL,

    -- Staff
    "OpenStaffID"               INTEGER         DEFAULT 0,
    "PaidStaffID"               INTEGER         DEFAULT 0,
    "CommStaffID"               INTEGER         DEFAULT 0,
    "VoidStaffID"               INTEGER         NOT NULL DEFAULT 0,
    "VoidReason"                TEXT            DEFAULT NULL,
    "VoidTime"                  TIMESTAMP       DEFAULT NULL,

    -- Status & mode
    "TransactionStatusID"       SMALLINT        NOT NULL DEFAULT 1,
    "SaleMode"                  SMALLINT        NOT NULL DEFAULT 1,
    "Deleted"                   SMALLINT        NOT NULL DEFAULT 0,
    "NoCustomer"                SMALLINT        DEFAULT 1,

    -- Discount
    "OtherPercentDiscount"      NUMERIC(5,2)    NOT NULL DEFAULT 0.00,
    "OtherAmountDiscount"       NUMERIC(10,4)   NOT NULL DEFAULT 0.0000,

    -- Pricing
    "ReceiptProductRetailPrice" NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,
    "ReceiptSalePrice"          NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,
    "ReceiptPayPrice"           NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,
    "ReceiptDiscount"           NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,
    "ReceiptTotalAmount"        NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,

    -- Tax
    "VATPercent"                NUMERIC(5,2)    NOT NULL DEFAULT 0.00,
    "TransactionVAT"            NUMERIC(18,6)   NOT NULL DEFAULT 0.000000,
    "TransactionExcludeVAT"     NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,
    "TransactionVATable"        NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,

    -- Service charge
    "ServiceChargePercent"      NUMERIC(5,2)    NOT NULL DEFAULT 0.00,
    "ServiceCharge"             NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,
    "ServiceChargeVAT"          NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,

    -- Other income
    "OtherIncome"               NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,
    "OtherIncomeVAT"            NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,

    -- Misc
    "TransactionNote"           VARCHAR(100)    DEFAULT NULL,
    "IsSplitTransaction"        SMALLINT        NOT NULL DEFAULT 0,
    "IsFromOtherTransaction"    SMALLINT        NOT NULL DEFAULT 0,
    "TransactionAdditionalType" SMALLINT        NOT NULL DEFAULT 0,
    "NoPrintBillDetail"         SMALLINT        NOT NULL DEFAULT 0,
    "BillDetailReferenceNo"     INTEGER         NOT NULL DEFAULT 0,

    -- Sync metadata
    outlet_code                 VARCHAR(20)     DEFAULT NULL,
    created_at                  TIMESTAMP       DEFAULT NULL,
    updated_at                  TIMESTAMP       DEFAULT NULL,

    PRIMARY KEY ("TransactionID")
);

CREATE INDEX IF NOT EXISTS idx_ordertransaction_saledate
    ON ordertransaction ("SaleDate");

CREATE INDEX IF NOT EXISTS idx_ordertransaction_shopid
    ON ordertransaction ("ShopID");

CREATE INDEX IF NOT EXISTS idx_ordertransaction_outlet
    ON ordertransaction (outlet_code);


-- ============================================================
-- TABLE: orderdetail
-- ============================================================
CREATE TABLE IF NOT EXISTS orderdetail (
    "OrderDetailID"     INTEGER         NOT NULL,
    "TransactionID"     INTEGER         NOT NULL REFERENCES ordertransaction ("TransactionID"),

    "ProductID"         INTEGER         NOT NULL DEFAULT 0,
    "ProductSetType"    INTEGER         NOT NULL DEFAULT 0,
    "OrderStatusID"     SMALLINT        NOT NULL DEFAULT 2,
    "SaleMode"          SMALLINT        NOT NULL DEFAULT 1,

    "Amount"            NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,
    "Price"             NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,
    "RetailPrice"       NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,
    "MinimumPrice"      NUMERIC(18,4)   NOT NULL DEFAULT 0.0000,
    subtotal            NUMERIC(18,4)   DEFAULT NULL,

    "Comment"           VARCHAR(255)    DEFAULT NULL,
    "OrderStaffID"      INTEGER         NOT NULL DEFAULT 0,
    "OrderTableID"      INTEGER         NOT NULL DEFAULT 0,
    "VoidStaffID"       INTEGER         NOT NULL DEFAULT 0,

    PRIMARY KEY ("OrderDetailID", "TransactionID")
);

CREATE INDEX IF NOT EXISTS idx_orderdetail_transactionid
    ON orderdetail ("TransactionID");

CREATE INDEX IF NOT EXISTS idx_orderdetail_productid
    ON orderdetail ("ProductID");


-- ============================================================
-- TABLE: api_keys
-- ============================================================
CREATE TABLE IF NOT EXISTS api_keys (
    key         VARCHAR(64)     NOT NULL,
    outlet_code VARCHAR(20)     NOT NULL,
    is_active   BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP       NOT NULL,

    PRIMARY KEY (key),
    UNIQUE (outlet_code)
);

CREATE INDEX IF NOT EXISTS idx_api_keys_outlet
    ON api_keys (outlet_code);