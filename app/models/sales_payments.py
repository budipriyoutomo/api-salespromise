from sqlalchemy import Column, Date, DateTime, ForeignKeyConstraint, Index, Integer, Numeric, SmallInteger, String

from app.database import Base


class SalesPayments(Base):
    """Baris pembayaran mentah per transaksi, dari view `vw_orderpaydetail` POS.

    Lihat docs/handoff-sync-api-payments.md dan migrasi 021.

    Kunci (outlet_code, TransactionID, ComputerID, PayDetailID) mengikuti PK
    tabel pembayaran POS. Jenis bayar dikunci per outlet lewat `PayTypeID`:
    ID dan nama jenis bayar milik POS outlet, jadi tidak pernah dibandingkan
    antar outlet berdasarkan nama. sync-api tidak menyimpan jenis sistem POS.

    Baris pembayaran satu transaksi selalu diganti utuh setiap kali POS
    mengirim key `payments` (`SalesService.sync_sales`).
    """

    __tablename__ = "orderpaydetail"
    __table_args__ = (
        ForeignKeyConstraint(
            ["TransactionID", "outlet_code"],
            ["ordertransaction.TransactionID", "ordertransaction.outlet_code"],
            name="orderpaydetail_transaction_fkey",
        ),
        # Rekap closing: penjumlahan per outlet + tanggal.
        Index("ix_orderpaydetail_outlet_saledate", "outlet_code", "SaleDate"),
    )

    outlet_code = Column("outlet_code", String(20), primary_key=True)
    transaction_id = Column("TransactionID", Integer, primary_key=True)
    computer_id = Column("ComputerID", Integer, primary_key=True)
    pay_detail_id = Column("PayDetailID", Integer, primary_key=True)

    sale_date = Column("SaleDate", Date, nullable=True)

    pay_type_id = Column("PayTypeID", Integer, nullable=False)
    pay_type_code = Column("PayTypeCode", String(50), nullable=True)
    pay_type_name = Column("PayTypeName", String(255), nullable=True)
    pay_type_display_name = Column("PayTypeDisplayName", String(255), nullable=True)

    # Nominal bersih tanpa kembalian; inilah yang dijumlahkan. Boleh negatif
    # (Voucher Adjustment) atau nol.
    amount = Column("Amount", Numeric(18, 4), nullable=False, default=0)
    # Informasi saja, tidak termasuk `Amount`.
    cash_change = Column("CashChange", Numeric(18, 4), nullable=False, default=0)

    # Informasi dari POS. Jangan dipakai untuk filter (handoff bagian 4).
    is_from_edc = Column("IsFromEDC", SmallInteger, nullable=False, default=0)
    is_sale = Column("IsSale", SmallInteger, nullable=False, default=0)
    is_other_receipt = Column("IsOtherReceipt", SmallInteger, nullable=False, default=0)

    received_at = Column("received_at", DateTime, nullable=False)
