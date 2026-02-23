/**
 * Web3 交互库：打赏 USDT、发帖费、钱包网络检测
 * 依赖：Web3（全局）、Toast、API_BASE
 */
(function () {
    'use strict';

    function getApiBase() {
        return (typeof window.API_BASE !== 'undefined') ? window.API_BASE : (window.location.origin + '/api');
    }

    /** 获取费用配置（发帖费、USDT 合约、收款地址等） */
    async function getFeesConfig() {
        var res = await fetch(getApiBase() + '/config/fees');
        var data = await res.json().catch(function () { return {}; });
        return data;
    }

    /**
     * 发送 USDT 转账（BEP-20）
     * @param {string} fromAddress - 当前用户地址
     * @param {string} toAddress - 收款地址
     * @param {number} amountUsdt - 金额（USDT）
     * @returns {Promise<string|null>} - 交易哈希或 null
     */
    async function sendUsdtTransfer(fromAddress, toAddress, amountUsdt) {
        var provider = window.BinanceChain || window.ethereum;
        if (!provider) {
            if (typeof Toast !== 'undefined') Toast.error('请安装钱包');
            return null;
        }
        var config = await getFeesConfig();
        if (!config.usdt_contract) {
            if (typeof Toast !== 'undefined') Toast.error('无法获取 USDT 合约配置');
            return null;
        }
        var web3 = new Web3(provider);
        var amountRaw = web3.utils.toBN(web3.utils.toWei(String(amountUsdt), 'ether'));
        var sig = web3.eth.abi.encodeFunctionSignature('transfer(address,uint256)');
        var paramsEnc = web3.eth.abi.encodeParameters(['address', 'uint256'], [toAddress, amountRaw]);
        var txData = sig + (paramsEnc.indexOf('0x') === 0 ? paramsEnc.slice(2) : paramsEnc);
        var txHash = await provider.request({
            method: 'eth_sendTransaction',
            params: [{
                to: config.usdt_contract,
                from: fromAddress,
                value: '0x0',
                data: txData,
                gas: web3.utils.toHex(100000)
            }]
        });
        return txHash || null;
    }

    /** 检测是否在支持的链上（BSC 56） */
    function checkChainId(provider) {
        return provider.request({ method: 'eth_chainId' }).then(function (chainId) {
            var id = parseInt(chainId, 16);
            return id === 56;
        }).catch(function () { return false; });
    }

    window.Web3Utils = {
        getApiBase: getApiBase,
        getFeesConfig: getFeesConfig,
        sendUsdtTransfer: sendUsdtTransfer,
        checkChainId: checkChainId
    };
})();
