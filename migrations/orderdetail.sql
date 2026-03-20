DROP TABLE IF EXISTS `orderdetail`;

CREATE TABLE `orderdetail` (
  `OrderDetailID` int(11) NOT NULL DEFAULT '0',
  `TransactionID` int(11) NOT NULL DEFAULT '0',
  `ProductID` int(11) NOT NULL DEFAULT '0',
  `ProductSetType` int(11) NOT NULL DEFAULT '0',
  `OrderStatusID` smallint(6) NOT NULL DEFAULT '2',
  `SaleMode` tinyint(4) NOT NULL DEFAULT '1',
  `Amount` decimal(18,4) NOT NULL DEFAULT '0.0000',
  `Price` decimal(18,4) NOT NULL DEFAULT '0.0000',
  `RetailPrice` decimal(18,4) NOT NULL DEFAULT '0.0000',
  `MinimumPrice` decimal(18,4) NOT NULL DEFAULT '0.0000',
  `Comment` varchar(255) DEFAULT NULL, 
  `OrderStaffID` int(11) NOT NULL DEFAULT '0', 
  `OrderTableID` int(11) NOT NULL DEFAULT '0',
  `VoidStaffID` int(11) NOT NULL DEFAULT '0',
  PRIMARY KEY (`OrderDetailID`,`TransactionID`),
) 